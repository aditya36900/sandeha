"""Image helpers shared by the engine: heatmap overlays, crops, media files."""
from __future__ import annotations

import base64
import io
from pathlib import Path

import numpy as np
from PIL import Image

MEDIA = Path(__file__).resolve().parents[2] / "data" / "media"
MEDIA.mkdir(parents=True, exist_ok=True)

_STOPS = np.array([[0.0, 0.0, 0.02], [0.30, 0.05, 0.45], [0.75, 0.15, 0.35], [0.99, 0.55, 0.05], [1.0, 0.98, 0.65]],
                  dtype=np.float32)


def colormap(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0, 1)
    pos = x * (len(_STOPS) - 1)
    i0 = np.clip(np.floor(pos).astype(int), 0, len(_STOPS) - 2)
    t = (pos - i0)[..., None]
    return _STOPS[i0] * (1 - t) + _STOPS[i0 + 1] * t


def overlay(img: Image.Image, heat: np.ndarray, lo: float, hi: float, size: int = 384) -> Image.Image:
    base = np.asarray(img.convert("RGB").resize((size, size))).astype(np.float32) / 255
    h = np.asarray(Image.fromarray(heat.astype(np.float32)).resize((size, size), Image.BILINEAR))
    n = np.clip((h - lo) / max(hi - lo, 1e-9), 0, 1)
    a = np.clip(n * 1.1, 0, 0.8)[..., None]
    out = base * (1 - a) + colormap(n) * a
    return Image.fromarray((out * 255).astype(np.uint8))


def save(img: Image.Image, rel: str, quality: int = 88) -> str:
    p = MEDIA / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(p, format="JPEG", quality=quality)
    return f"/media/{rel}"


def load_media(url: str | None) -> Image.Image | None:
    """Inverse of save(): '/media/<rel>' -> the stored image, or None."""
    if not url or not url.startswith("/media/"):
        return None
    p = MEDIA / url[len("/media/"):]
    return Image.open(p).convert("RGB") if p.exists() else None


def b64(img: Image.Image, size: int = 192) -> str:
    buf = io.BytesIO()
    img.convert("RGB").resize((size, size)).save(buf, format="JPEG", quality=82)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def crop_pct(img: Image.Image, x: float, y: float, r: float = 0.09, size: int = 160) -> Image.Image:
    """Square crop centred at (x, y) in [0, 1] image coordinates."""
    w, h = img.size
    cx, cy, rr = x * w, y * h, r * w
    box = (int(max(0, cx - rr)), int(max(0, cy - rr)), int(min(w, cx + rr)), int(min(h, cy + rr)))
    return img.crop(box).resize((size, size))


def sharpness(img: Image.Image) -> float:
    g = np.asarray(img.convert("L").resize((256, 256))).astype(np.float32)
    lap = g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:] - 4 * g[1:-1, 1:-1]
    return float(lap.var())


def brightness(img: Image.Image) -> float:
    return float(np.asarray(img.convert("L").resize((128, 128))).mean() / 255)
