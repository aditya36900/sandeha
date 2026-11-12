"""3D relief from a single photo (Depth Anything V2 Small, Apache-2.0) for products without camera poses.

Multi-view products get a true space-carved twin (twin.py). Fixed-camera products and user uploads
get a 2.5D relief: monocular relative depth lifted into a coloured point surface, so defects can be
shown *on the part's shape* even when only one viewpoint exists.
"""
from __future__ import annotations

import threading

import numpy as np
from PIL import Image

_PIPE = None
_LOCK = threading.Lock()
MODEL = "depth-anything/Depth-Anything-V2-Small-hf"


def _pipe():
    global _PIPE
    with _LOCK:
        if _PIPE is None:
            import torch
            from transformers import pipeline

            _PIPE = pipeline("depth-estimation", model=MODEL, device=0 if torch.cuda.is_available() else -1)
        return _PIPE


def estimate(img: Image.Image) -> np.ndarray:
    """Relative depth in [0, 1], 1 = nearest to the camera."""
    out = _pipe()(img.convert("RGB"))
    d = np.asarray(out["predicted_depth"]).squeeze().astype(np.float32) if "predicted_depth" in out else \
        np.asarray(out["depth"], np.float32)
    d = np.asarray(Image.fromarray(d).resize(img.size, Image.BILINEAR))
    lo, hi = np.percentile(d, 2), np.percentile(d, 98)
    return np.clip((d - lo) / max(hi - lo, 1e-6), 0, 1)


def relief_cloud(img: Image.Image, depth: np.ndarray, grid: int = 150, height: float = 0.35) -> dict:
    """Coloured point surface in the twin's coordinate convention (x right, z up, y away from the camera)."""
    w, h = img.size
    aspect = w / h
    small = np.asarray(img.convert("RGB").resize((grid, grid), Image.BILINEAR), np.float32) / 255
    dz = np.asarray(Image.fromarray(depth).resize((grid, grid), Image.BILINEAR))
    v, u = np.mgrid[0:grid, 0:grid] / (grid - 1)
    x = (u - 0.5) * 2 * min(aspect, 1.6)
    z = (0.5 - v) * 2
    y = -height * dz
    gy, gx = np.gradient(dz * height * grid / 2)
    n = np.stack([-gx, -np.ones_like(gx), gy], -1)  # rough surface normals (for colouring only)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    pos = np.stack([x, y, z], -1).reshape(-1, 3)
    return {"positions": pos.round(4).reshape(-1).tolist(), "colors": small.reshape(-1, 3).round(3).reshape(-1).tolist(),
            "normals": n.reshape(-1, 3).round(3).reshape(-1).tolist(), "count": int(grid * grid), "occupied": int(grid * grid),
            "cameras": [], "seen": 1.0, "relief": True, "grid": grid}


def sample_heat(heat: np.ndarray, grid: int) -> list:
    """Heat map (image-aligned) resampled to the relief grid, in the same point order as relief_cloud."""
    return np.asarray(Image.fromarray(heat.astype(np.float32)).resize((grid, grid), Image.BILINEAR)).reshape(-1).tolist()
