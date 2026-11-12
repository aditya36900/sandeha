"""Second detector: the statistical golden board.

The camera is fixed, so after alignment every pixel of the 30 good boards has a mean colour and a spread. A new
board's per-pixel deviation (a z-score map: how many spreads away each pixel is) is an independent signal from the
DINOv2 patch memory, and it is how classical AOI works. The two are fused at the patch level so every downstream
step (score, heatmap, regions, components, calibration) sees one consistent map; references are scored leave-one-out
so calibration stays honest.
"""
from __future__ import annotations

import cv2
import numpy as np
import torch
from PIL import Image

from .board import align, lab, to_work

Z_START = 2.5  # deviations below this many spreads are normal variation
FLOOR = np.array([3.0, 1.5, 1.5], np.float32)  # minimum spread per Lab channel (sensor noise), so z never explodes
SMOOTH = 2.0


class GoldenStats:
    def __init__(self, bm, sum_: np.ndarray, sq: np.ndarray, n: int, warps: list[np.ndarray]):
        self.bm = bm
        self.sum, self.sq, self.n = sum_, sq, n
        self.warps = warps  # per reference, golden -> reference-photo warp (for leave-one-out)
        self.board = bm.board.astype(np.float32)

    @classmethod
    def build(cls, bm, refs: list[Image.Image]) -> "GoldenStats":
        labs, warps = [], []
        for im in refs:
            a, w = align(to_work(im), bm.golden)
            labs.append(lab(a))
            warps.append(w)
        stack = np.stack(labs)
        return cls(bm, stack.sum(0), (stack ** 2).sum(0), len(labs), warps)

    def zmap(self, aligned_lab: np.ndarray, exclude: int | None = None) -> np.ndarray:
        """z-score map in the golden frame. exclude=i removes reference i from the statistics (leave-one-out)."""
        s, q, n = self.sum, self.sq, self.n
        if exclude is not None and n > 2:
            s, q, n = s - aligned_lab, q - aligned_lab ** 2, n - 1
        mean = s / n
        var = np.maximum(q / n - mean ** 2, 0.0)
        std = np.sqrt(var) + FLOOR
        z = np.abs(aligned_lab - mean) / std
        z = np.sqrt((z ** 2).mean(axis=2))  # one deviation per pixel across L, a, b
        z = cv2.GaussianBlur(z, (0, 0), SMOOTH) * self.board
        return np.maximum(z - Z_START, 0.0)

    def patch_map(self, img: Image.Image, hw: tuple[int, int], exclude: int | None = None) -> np.ndarray:
        """Deviation on the backbone's patch grid, in the query image's own frame (block max: small defects count)."""
        work = to_work(img)
        if exclude is not None:
            warp = self.warps[exclude]
            a = cv2.warpAffine(work, warp, (self.bm.golden.shape[1], self.bm.golden.shape[0]),
                               flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)
        else:
            a, warp = align(work, self.bm.golden)
        z = self.zmap(lab(a), exclude)
        H, W = work.shape[:2]
        zq = cv2.warpAffine(z, warp, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)  # back to the query frame
        h, w = hw
        zs = cv2.resize(zq, (w * 4, h * 4), interpolation=cv2.INTER_AREA)
        return zs.reshape(h, 4, w, 4).max(axis=(1, 3))

    def diff_image(self, img: Image.Image, size: int = 384) -> Image.Image:
        """The deviation map painted over this board, for the blink comparator."""
        a, _ = align(to_work(img), self.bm.golden)
        z = self.zmap(lab(a))
        zn = np.clip(z / 2.0, 0, 1) ** 0.7  # 2 spreads beyond normal = fully lit
        base = a.astype(np.float32) / 255 * 0.55  # dim the board so the deviation reads
        col = np.stack([np.ones_like(zn), 0.55 - 0.35 * zn, 0.15 * (1 - zn)], -1)  # amber -> orange-red
        out = base * (1 - 0.9 * zn[..., None]) + col * 0.9 * zn[..., None]
        return Image.fromarray((out * 255).astype(np.uint8)).resize((size, int(size * a.shape[0] / a.shape[1])), Image.BILINEAR)

    def golden_image(self, size: int = 384) -> Image.Image:
        g = self.bm.golden
        return Image.fromarray(g).resize((size, int(size * g.shape[0] / g.shape[1])), Image.BILINEAR)


def fuse(dist: torch.Tensor, zpatch: np.ndarray, gain: float) -> torch.Tensor:
    """dist: (1, h*w) patch distances; zpatch: (h, w) deviations. gain converts spreads into distance units."""
    z = torch.from_numpy(zpatch.reshape(1, -1).astype(np.float32)).to(dist.device)
    return dist + gain * z
