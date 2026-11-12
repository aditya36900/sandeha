"""Stage UNDERSTAND: frozen DINOv2 patch features (no training, works from a handful of images)."""
from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)


@dataclass
class PatchGrid:
    feats: torch.Tensor  # (N, h*w, d) L2-normalised patch features
    cls: torch.Tensor  # (N, d) normalised global embedding
    hw: tuple[int, int]
    fg: torch.Tensor  # (N, h*w) bool foreground mask (object vs background)


class Backbone:
    """DINOv2 ViT (facebook/dinov2-*) from Hugging Face, Apache-2.0."""

    _instances: dict[str, "Backbone"] = {}
    _lock = threading.Lock()

    def __init__(self, name: str = "facebook/dinov2-small", resolution: int = 448):
        from transformers import AutoModel

        self.name, self.resolution = name, resolution
        self.model = AutoModel.from_pretrained(name).to(DEVICE).eval()
        if DEVICE == "cuda":
            self.model = self.model.half()
        self.patch = self.model.config.patch_size
        self.dim = self.model.config.hidden_size

    @classmethod
    def get(cls, name: str = "facebook/dinov2-small", resolution: int = 448) -> "Backbone":
        key = f"{name}@{resolution}"
        with cls._lock:
            if key not in cls._instances:
                cls._instances[key] = cls(name, resolution)
            return cls._instances[key]

    def to_tensor(self, images: list[Image.Image]) -> torch.Tensor:
        r = self.resolution
        arr = np.stack([np.asarray(im.convert("RGB").resize((r, r), Image.BICUBIC), dtype=np.float32) / 255.0
                        for im in images])
        x = torch.from_numpy(arr).permute(0, 3, 1, 2)
        return (x - MEAN) / STD

    @torch.no_grad()
    def __call__(self, images: list[Image.Image], batch: int = 8, masking: bool = True) -> PatchGrid:
        feats, clss = [], []
        for i in range(0, len(images), batch):
            x = self.to_tensor(images[i:i + batch]).to(DEVICE)
            if DEVICE == "cuda":
                x = x.half()
            out = self.model(pixel_values=x).last_hidden_state.float()
            clss.append(F.normalize(out[:, 0], dim=-1))
            feats.append(F.normalize(out[:, 1:], dim=-1))
        f = torch.cat(feats)
        h = w = self.resolution // self.patch
        fg = foreground(f, h, w) if masking else torch.ones(f.shape[:2], dtype=torch.bool, device=f.device)
        return PatchGrid(feats=f, cls=torch.cat(clss), hw=(h, w), fg=fg)


def foreground(f: torch.Tensor, h: int, w: int) -> torch.Tensor:
    """Zero-shot object mask: sign of the first principal component of patch features (AnomalyDINO-style).
    The component is oriented so the image centre counts as foreground."""
    n, p, d = f.shape
    flat = f.reshape(-1, d)
    mu = flat.mean(0, keepdim=True)
    _, _, v = torch.pca_lowrank(flat - mu, q=3)
    pc = ((flat - mu) @ v[:, 0]).reshape(n, h, w)
    c = pc[:, h // 4: 3 * h // 4, w // 4: 3 * w // 4].mean()
    if c < 0:
        pc = -pc
    mask = pc > 0
    # dilate one patch so object borders are always inspected
    m = F.max_pool2d(mask.float().unsqueeze(1), 3, 1, 1).squeeze(1) > 0
    # if masking failed (texture-like product), inspect everything
    frac = m.float().mean(dim=(1, 2))
    m[frac < 0.05] = True
    m[frac > 0.97] = True
    return m.reshape(n, p)
