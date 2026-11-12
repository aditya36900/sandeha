"""Defect Imagination Engine: procedurally synthesise plausible defects on good images.

Used to (1) calibrate the escape side of the trust policy before many real defects exist,
(2) stress-test the detector ("defects I'm afraid of"), and (3) measure the minimum detectable
defect size per region (Blind-Spot Atlas). Every synthetic defect comes with an exact mask,
a type and a physical size, so detection can be measured, not guessed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

DEFECT_TYPES = ("scratch", "stain", "crack", "missing", "burr", "fiber", "cutpaste")


@dataclass
class Imagined:
    image: Image.Image
    mask: np.ndarray  # (H, W) uint8 {0,1}
    kind: str
    size_px: float  # characteristic size (length or diameter) in pixels
    center: tuple[float, float]  # (x, y) pixels


def object_mask(img: Image.Image, fg_grid: np.ndarray | None = None) -> np.ndarray:
    """Where defects may be placed. Uses the backbone foreground grid when given, otherwise a
    background-colour heuristic (border colour = background)."""
    a = np.asarray(img.convert("RGB")).astype(np.int16)
    h, w = a.shape[:2]
    if fg_grid is not None:
        g = Image.fromarray((fg_grid.astype(np.uint8) * 255)).resize((w, h), Image.NEAREST)
        m = np.asarray(g) > 0
        if 0.05 < m.mean() < 0.97:
            return m
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    bg = np.median(border, axis=0)
    m = np.abs(a - bg).sum(-1) > 45
    return m if m.mean() > 0.03 else np.ones((h, w), bool)


def _erode(m: np.ndarray, r: int) -> np.ndarray:
    """Pixels at least r px inside the mask (distance transform: O(N), independent of r)."""
    import cv2

    if r <= 0:
        return m.astype(bool)
    d = cv2.distanceTransform(m.astype(np.uint8), cv2.DIST_L2, 3)
    return d > r


def _pick_center(rng, m: np.ndarray, margin: int):
    inner = _erode(m, margin) if margin > 0 else m
    ys, xs = np.nonzero(inner if inner.any() else m)
    i = int(rng.integers(len(xs)))
    return float(xs[i]), float(ys[i])


def _noise_blob(rng, h, w, cx, cy, r) -> np.ndarray:
    """Irregular blob: radial noise around a circle."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    ang = np.arctan2(yy - cy, xx - cx)
    k = rng.integers(3, 7)
    rad = r * (1 + sum(rng.uniform(0.05, 0.25) * np.sin(j * ang + rng.uniform(0, 6.28)) for j in range(1, k)))
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    return np.clip((rad - d) / max(r * 0.25, 1.0), 0, 1)


def _polyline(rng, cx, cy, length, jitter, steps=8):
    ang = rng.uniform(0, math.pi)
    pts = [(cx - math.cos(ang) * length / 2, cy - math.sin(ang) * length / 2)]
    seg = length / steps
    for _ in range(steps):
        ang += rng.uniform(-jitter, jitter)
        pts.append((pts[-1][0] + math.cos(ang) * seg, pts[-1][1] + math.sin(ang) * seg))
    return pts


MAX_SIDE = 512


def imagine(img: Image.Image, kind: str, size_px: float, rng: np.random.Generator,
            mask: np.ndarray | None = None, center: tuple[float, float] | None = None,
            donor: Image.Image | None = None) -> Imagined:
    img = img.convert("RGB")
    if max(img.size) > MAX_SIDE:  # imagine at (roughly) the resolution the model sees
        f = MAX_SIDE / max(img.size)
        img = img.resize((int(img.width * f), int(img.height * f)), Image.BILINEAR)
        size_px *= f
        if center is not None:
            center = (center[0] * f, center[1] * f)
        if mask is not None:
            mask = np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).resize(img.size, Image.NEAREST)) > 0
    w, h = img.size
    m = mask if mask is not None else object_mask(img)
    cx, cy = center or _pick_center(rng, m, int(size_px / 2) + 2)
    base = np.asarray(img).astype(np.float32) / 255.0
    local = base[max(0, int(cy) - 8):int(cy) + 8, max(0, int(cx) - 8):int(cx) + 8].reshape(-1, 3).mean(0)
    alpha = np.zeros((h, w), np.float32)
    color = np.zeros(3, np.float32)

    if kind in ("scratch", "crack", "fiber"):
        layer = Image.new("L", (w, h), 0)
        dr = ImageDraw.Draw(layer)
        if kind == "scratch":
            pts = _polyline(rng, cx, cy, size_px, 0.08, 6)
            dr.line(pts, fill=255, width=max(1, int(round(size_px / 40)) + 1))
            color = np.clip(local + (0.35 if local.mean() < 0.5 else -0.35), 0, 1)
        elif kind == "crack":
            pts = _polyline(rng, cx, cy, size_px, 0.7, 10)
            dr.line(pts, fill=255, width=max(1, int(round(size_px / 50)) + 1))
            for _ in range(int(rng.integers(1, 3))):  # branches
                j = int(rng.integers(2, len(pts) - 2))
                br = _polyline(rng, pts[j][0], pts[j][1], size_px * 0.35, 0.8, 4)
                dr.line(br, fill=255, width=1)
            color = local * 0.25
        else:  # fiber / hair: long, thin, curly foreign object
            pts = _polyline(rng, cx, cy, size_px * 1.4, 0.5, 14)
            dr.line(pts, fill=255, width=1)
            color = np.array([0.08, 0.06, 0.05]) if local.mean() > 0.4 else np.array([0.85, 0.82, 0.75])
        layer = layer.filter(ImageFilter.GaussianBlur(0.6))
        alpha = np.asarray(layer).astype(np.float32) / 255.0
    elif kind == "stain":
        alpha = _noise_blob(rng, h, w, cx, cy, size_px / 2) * rng.uniform(0.45, 0.75)
        tint = rng.choice([np.array([0.55, 0.42, 0.25]), np.array([0.35, 0.35, 0.38]), np.array([0.7, 0.55, 0.2])])
        color = np.clip(local * tint * 1.4, 0, 1)
    elif kind == "missing":
        a = np.asarray(img).astype(np.float32)
        border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]]) / 255.0
        bgc = np.median(border, axis=0)
        # bite out of the object edge: move centre towards the nearest boundary
        edge = m & ~_erode(m, 3)
        ys, xs = np.nonzero(edge)
        if len(xs):
            i = int(np.argmin((xs - cx) ** 2 + (ys - cy) ** 2))
            cx, cy = float(xs[i]), float(ys[i])
        alpha = _noise_blob(rng, h, w, cx, cy, size_px / 2)
        color = bgc
    elif kind == "burr":
        alpha = _noise_blob(rng, h, w, cx, cy, size_px / 2)
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        shade = np.clip(1 + 0.6 * ((xx - cx) - (yy - cy)) / max(size_px, 1), 0.4, 1.6)[..., None]
        out = base * (1 - alpha[..., None]) + np.clip(local * shade, 0, 1) * alpha[..., None]
        msk = (alpha > 0.3).astype(np.uint8)
        return Imagined(Image.fromarray((out * 255).astype(np.uint8)), msk, kind, size_px, (cx, cy))
    elif kind == "cutpaste":
        src = (donor or img).convert("RGB")
        s = max(4, int(size_px))
        sx, sy = rng.integers(0, max(1, src.width - s)), rng.integers(0, max(1, src.height - s))
        patch = src.crop((sx, sy, sx + s, sy + s)).rotate(float(rng.uniform(0, 360)))
        patch = patch.resize((s, s))
        out = img.copy()
        blob = Image.fromarray((_noise_blob(rng, s, s, s / 2, s / 2, s / 2.3) * 255).astype(np.uint8))
        out.paste(patch, (int(cx - s / 2), int(cy - s / 2)), blob)
        msk = np.zeros((h, w), np.uint8)
        bb = (np.asarray(blob) > 80).astype(np.uint8)
        x0, y0 = int(cx - s / 2), int(cy - s / 2)
        ys0, xs0 = max(0, y0), max(0, x0)
        ys1, xs1 = min(h, y0 + s), min(w, x0 + s)
        msk[ys0:ys1, xs0:xs1] = bb[ys0 - y0:ys1 - y0, xs0 - x0:xs1 - x0]
        return Imagined(out, msk, kind, size_px, (cx, cy))
    else:
        raise ValueError(kind)

    a3 = alpha[..., None]
    out = base * (1 - a3) + color[None, None, :] * a3
    if kind != "missing":  # keep defects on the part
        keep = m[..., None]
        out = np.where(keep, out, base)
        alpha = alpha * m
    msk = (alpha > 0.25).astype(np.uint8)
    return Imagined(Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8)), msk, kind, size_px, (cx, cy))


def imagine_set(goods: list[Image.Image], n: int, rng: np.random.Generator, sizes=(0.04, 0.12),
                kinds=DEFECT_TYPES, masks: list[np.ndarray] | None = None) -> list[Imagined]:
    """n defects spread over references, kinds and sizes (sizes as a fraction of image width)."""
    out = []
    for i in range(n):
        j = i % len(goods)
        g = goods[j]
        kind = kinds[i % len(kinds)]
        size = float(rng.uniform(*sizes)) * g.width
        donor = goods[(j + 1) % len(goods)]
        out.append(imagine(g, kind, size, rng, mask=None if masks is None else masks[j], donor=donor))
    return out
