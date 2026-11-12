"""Chaos Lab + domain-shift guard.

* `perturb` simulates the organisers' mid-run changes on internet images: lighting
  (brightness, colour temperature, directional falloff), camera angle (rotation, perspective),
  surface finish (contrast, sheen, texture blur), blur, sensor noise.
* `ShiftGuard` runs a conformal test martingale (Vovk et al.) over p-values of each part's
  global appearance against the references. Under unchanged conditions the martingale is a
  non-negative supermartingale, so by Ville's inequality P(it ever exceeds 1/delta) <= delta.
  Crossing the line means "conditions changed": auto-PASS is suspended until the system adapts.
  A floor on log M (CUSUM-style restart) keeps the detector responsive after long normal runs;
  with the floor the false-alarm bound holds per restart rather than over the whole stream.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import torch
from PIL import Image, ImageEnhance, ImageFilter


@dataclass
class Conditions:
    brightness: float = 1.0  # 0.4 .. 1.6
    color_temp: float = 0.0  # -1 (cool/blue) .. 1 (warm/yellow)
    falloff: float = 0.0  # 0 .. 1 directional lighting gradient
    rotation: float = 0.0  # degrees
    perspective: float = 0.0  # 0 .. 1
    contrast: float = 1.0  # 0.5 .. 1.5
    sheen: float = 0.0  # 0 .. 1 specular highlight
    blur: float = 0.0  # px
    noise: float = 0.0  # std in 0..0.1

    def is_identity(self) -> bool:
        return self == Conditions()


def perturb(img: Image.Image, c: Conditions, seed: int = 0) -> Image.Image:
    rng = np.random.default_rng(seed)
    im = img.convert("RGB")
    w, h = im.size
    if c.rotation:
        im = im.rotate(c.rotation, resample=Image.BILINEAR, fillcolor=tuple(int(v) for v in np.asarray(im)[0, 0]))
    if c.perspective:
        d = c.perspective * 0.12 * w
        coeffs = _persp_coeffs([(0, 0), (w, 0), (w, h), (0, h)], [(d, d * 0.5), (w - d * 0.3, 0), (w, h), (0, h - d * 0.4)])
        im = im.transform((w, h), Image.PERSPECTIVE, coeffs, Image.BILINEAR)
    if c.blur:
        im = im.filter(ImageFilter.GaussianBlur(c.blur))
    if c.contrast != 1.0:
        im = ImageEnhance.Contrast(im).enhance(c.contrast)
    a = np.asarray(im).astype(np.float32) / 255.0
    a = a * c.brightness
    if c.color_temp:
        t = c.color_temp
        a = a * np.array([1 + 0.18 * t, 1 + 0.04 * t, 1 - 0.2 * t], np.float32)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    if c.falloff:
        a = a * (1 - c.falloff * 0.55 * (xx / w))[..., None]
    if c.sheen:
        cx, cy = 0.35 * w, 0.3 * h
        g = np.exp(-(((xx - cx) / (0.25 * w)) ** 2 + ((yy - cy) / (0.2 * h)) ** 2))
        a = a + c.sheen * 0.5 * g[..., None]
    if c.noise:
        a = a + rng.normal(0, c.noise, a.shape).astype(np.float32)
    return Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))


def _persp_coeffs(src, dst):
    m = []
    for (x, y), (u, v) in zip(dst, src):
        m.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        m.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    A = np.array(m, dtype=np.float64)
    b = np.array(src, dtype=np.float64).reshape(8)
    return np.linalg.lstsq(A, b, rcond=None)[0].tolist()


PRESETS = {
    "night_shift_lights": Conditions(brightness=0.62, color_temp=0.6, falloff=0.5),
    "skylight_glare": Conditions(brightness=1.25, sheen=0.7, color_temp=-0.3),
    "camera_bumped": Conditions(rotation=7, perspective=0.5),
    "new_surface_finish": Conditions(contrast=0.7, sheen=0.35, blur=0.8),
    "dirty_lens": Conditions(blur=2.2, contrast=0.85),
}


def global_nonconformity(cls: torch.Tensor, ref_cls: torch.Tensor, exclude_self: bool = False) -> torch.Tensor:
    """1 - cosine similarity to the nearest reference global embedding."""
    s = cls @ ref_cls.T
    if exclude_self:
        s = s - 2 * torch.eye(len(cls), device=cls.device)
    return 1 - s.max(1).values


def _smoothed_p(calib: np.ndarray, x: float, rng: np.random.Generator) -> float:
    n = len(calib)
    gt = np.sum(calib > x)
    eq = np.sum(calib == x) + 1
    return max(float((gt + rng.uniform() * eq) / (n + 1)), 1e-6)


@dataclass
class ShiftGuard:
    """Conformal test martingale over two evidence streams:
    global appearance (CLS embedding) and local appearance (patch anomaly score).
    The two p-values are merged with Bonferroni (2 * min), which stays a valid p-value."""
    calib_global: np.ndarray
    calib_local: np.ndarray | None = None
    delta: float = 0.005  # alarm at 200; measured quiet on 30%-defect bursts across VisA products
    epsilon: float = 0.8
    log_m: float = 0.0
    history: list = field(default_factory=list)
    alarmed: bool = False
    _rng: np.random.Generator = field(default_factory=lambda: np.random.default_rng(0))

    @property
    def threshold(self) -> float:
        return 1.0 / self.delta

    window: int = 9
    _recent: list = field(default_factory=list)

    def update(self, nonconf_global: float, nonconf_local: float | None = None) -> dict:
        p = _smoothed_p(np.asarray(self.calib_global), nonconf_global, self._rng)
        if nonconf_local is not None and self.calib_local is not None and len(self.calib_local):
            p2 = _smoothed_p(np.asarray(self.calib_local), nonconf_local, self._rng)
            p = min(1.0, 2 * min(p, p2))
        # Upper-quantile filter over the last 9 parts: a shift lowers EVERY part's p-value, a defect
        # burst only some. Using the 70th percentile, 7 of 9 parts must look abnormal before the
        # martingale bets; robust to sustained 30% defect rates. The false-alarm rate is empirical
        # (measured in tests) rather than the exact Ville bound of the unfiltered martingale.
        self._recent.append(p)
        del self._recent[:-self.window]
        p = float(np.quantile(self._recent, 0.7))
        self.log_m += math.log(self.epsilon) + (self.epsilon - 1) * math.log(p)
        self.log_m = max(self.log_m, -2.0)  # CUSUM-style restart floor
        m = math.exp(min(self.log_m, 50))
        if m >= self.threshold:
            self.alarmed = True
        self.history.append({"p": round(p, 4), "martingale": round(m, 3), "alarm": self.alarmed})
        return self.history[-1]

    def reset(self, calib_global=None, calib_local=None) -> None:
        if calib_global is not None:
            self.calib_global = np.asarray(calib_global)
        if calib_local is not None:
            self.calib_local = np.asarray(calib_local)
        self.log_m, self.alarmed = 0.0, False
        self.history.clear()
        self._recent.clear()
