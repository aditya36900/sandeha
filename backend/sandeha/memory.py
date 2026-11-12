"""Stage COMPARE: few-shot patch memory with nearest-neighbour anomaly maps (GPU)."""
from __future__ import annotations

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from .backbone import Backbone, PatchGrid


def augment(images: list[Image.Image]) -> list[Image.Image]:
    """Few-shot trick: rotations/flips multiply the reference memory without new photos."""
    out = []
    for im in images:
        out += [im, im.transpose(Image.FLIP_LEFT_RIGHT), im.rotate(90), im.rotate(180), im.rotate(270)]
    return out


class PatchMemory:
    def __init__(self, backbone: Backbone, augment_refs: bool = True, top_frac: float = 0.01):
        self.bb = backbone
        self.augment_refs = augment_refs
        self.top_frac = top_frac
        self.bank: torch.Tensor | None = None  # (M, d)
        self.bank_src: torch.Tensor | None = None  # (M,) reference image index (for leave-one-out)
        self.ref_cls: torch.Tensor | None = None
        self.masking = True
        self.hw = (0, 0)

    def fit(self, refs: list[Image.Image], masking: bool = True) -> "PatchMemory":
        self.masking = masking
        k = 5 if self.augment_refs else 1
        imgs = augment(refs) if self.augment_refs else refs
        g = self.bb(imgs, masking=masking)
        self.hw = g.hw
        src = torch.arange(len(refs), device=g.feats.device).repeat_interleave(k)
        keep = g.fg  # only object patches go to memory
        self.bank = g.feats[keep]
        self.bank_src = src.unsqueeze(1).expand_as(keep)[keep]
        self.ref_cls = g.cls[::k]
        return self

    @torch.no_grad()
    def coreset(self, fraction: float = 0.1, seed: int = 0) -> dict:
        """Keep only the most representative patches (greedy k-centre on a random projection, PatchCore-style).
        10x less memory, faster search, almost no accuracy loss - measured, see scripts/edge_profile_eval.py."""
        bank = self.bank.float()
        m = bank.shape[0]
        k = max(256, int(m * fraction))
        if k >= m:
            return {"before": m, "after": m}
        g = torch.Generator(device="cpu").manual_seed(seed)
        proj = torch.randn(bank.shape[1], 128, generator=g).to(bank.device)
        x = bank @ proj
        chosen = torch.empty(k, dtype=torch.long, device=bank.device)
        chosen[0] = int(torch.randint(m, (1,), generator=g))
        mind = torch.cdist(x, x[chosen[0]:chosen[0] + 1]).squeeze(1)
        for i in range(1, k):
            j = int(mind.argmax())
            chosen[i] = j
            mind = torch.minimum(mind, torch.cdist(x, x[j:j + 1]).squeeze(1))
        self.bank = self.bank[chosen]
        self.bank_src = self.bank_src[chosen]
        return {"before": m, "after": k}

    def add(self, refs: list[Image.Image], src_offset: int | None = None) -> int:
        """Continual learning: append verified-good references. Nothing is overwritten (no forgetting)."""
        g = self.bb(refs, masking=self.masking)
        base = int(self.bank_src.max().item()) + 1 if src_offset is None else src_offset
        src = torch.arange(len(refs), device=g.feats.device) + base
        keep = g.fg
        self.bank = torch.cat([self.bank, g.feats[keep]])
        self.bank_src = torch.cat([self.bank_src, src.unsqueeze(1).expand_as(keep)[keep]])
        self.ref_cls = torch.cat([self.ref_cls, g.cls])
        return int(keep.sum())

    @torch.no_grad()
    def distances(self, g: PatchGrid, exclude_src: list[int] | None = None, chunk: int = 4096) -> torch.Tensor:
        """Cosine distance of every patch to its nearest reference patch -> (N, h*w)."""
        n, p, d = g.feats.shape
        out = torch.empty(n, p, device=g.feats.device)
        bank = self.bank.half() if self.bank.is_cuda else self.bank
        for i in range(n):
            q = g.feats[i].half() if bank.dtype == torch.float16 else g.feats[i]
            sims = []
            for j in range(0, bank.shape[0], chunk * 8):
                s = q @ bank[j:j + chunk * 8].T
                if exclude_src is not None:
                    s = s.masked_fill(self.bank_src[j:j + chunk * 8].unsqueeze(0) == exclude_src[i], -2)
                sims.append(s.max(dim=1).values)
            out[i] = 1 - torch.stack(sims, 1).max(1).values.float()
        return out

    def score(self, dist: torch.Tensor, fg: torch.Tensor) -> torch.Tensor:
        """Image score: mean of the top-1% foreground patch distances."""
        d = dist.masked_fill(~fg, 0.0)
        k = max(1, int(round(self.top_frac * d.shape[1])))
        return d.topk(k, dim=1).values.mean(1)

    def anomaly_maps(self, dist: torch.Tensor, fg: torch.Tensor, size: int) -> np.ndarray:
        h, w = self.hw
        m = dist.masked_fill(~fg, 0.0).reshape(-1, 1, h, w)
        m = F.interpolate(m, size=(size, size), mode="bilinear", align_corners=False)
        # light smoothing
        m = F.avg_pool2d(m, 9, 1, 4)
        return m.squeeze(1).cpu().numpy()

    def inspect(self, images: list[Image.Image], exclude_src: list[int] | None = None):
        g = self.bb(images, masking=self.masking)
        dist = self.distances(g, exclude_src)
        return g, dist, self.score(dist, g.fg)


def loo_scores(mem: "PatchMemory", refs: list[Image.Image]) -> torch.Tensor:
    """Leave-one-out scores of the reference images (each scored against all *other* references).
    These are exchangeable with future good parts, which is what conformal calibration needs."""
    _, _, sc = mem.inspect(refs, exclude_src=list(range(len(refs))))
    return sc


@torch.no_grad()
def deviation_signature(mem: "PatchMemory", feats: torch.Tensor, dist: torch.Tensor, k: int = 8) -> torch.Tensor:
    """Defect fingerprint = mean direction in which the most anomalous patches deviate from their
    nearest normal patch. Product-relative, so it transfers between plants making the same product,
    and it is 384 numbers: no pixels leave the plant."""
    k = min(k, len(dist))
    idx = dist.topk(k).indices
    q = feats[idx]
    bank = mem.bank
    sims = (q.half() if bank.dtype == torch.float16 else q) @ bank.T
    nn = bank[sims.argmax(1)].float()
    r = torch.nn.functional.normalize(q.float() - nn, dim=-1).mean(0)
    return torch.nn.functional.normalize(r, dim=0)
