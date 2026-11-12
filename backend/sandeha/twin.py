"""Digital Twin Genesis: a 3D model of the product carved from ~30 posed photos.

Space carving (visual hull): every voxel that projects outside the object silhouette in any
view is removed. With the MAD-Sim camera poses this runs in well under a second on a GPU and
can be streamed view-by-view so the dashboard shows the object *emerging* from a block.
Surface points are coloured from the camera that sees them most head-on, and anomaly maps
from inspected images can be projected back onto the twin.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


@dataclass
class View:
    image: np.ndarray  # (H, W, 3) uint8
    c2w: np.ndarray  # (4, 4) camera-to-world (Blender/NeRF convention: -z forward, +y up)
    fov_x: float


def silhouette(img: np.ndarray, bg: int = 255, tol: int = 40) -> np.ndarray:
    diff = np.abs(img.astype(np.int16) - bg).sum(-1)
    m = torch.from_numpy((diff > tol).astype(np.float32))[None, None]
    m = F.max_pool2d(m, 5, 1, 2)  # close small holes
    m = -F.max_pool2d(-m, 5, 1, 2)
    return m[0, 0].numpy() > 0.5


class Twin:
    def __init__(self, resolution: int = 128, bound: float = 1.2):
        self.res, self.bound = resolution, bound
        lin = torch.linspace(-bound, bound, resolution, device=DEVICE)
        zz, yy, xx = torch.meshgrid(lin, lin, lin, indexing="ij")
        self.xyz = torch.stack([xx, yy, zz], -1).reshape(-1, 3)
        self.occ = torch.ones(self.xyz.shape[0], dtype=torch.bool, device=DEVICE)
        self.views: list[View] = []
        self._masks: list[torch.Tensor] = []

    # ------------------------------------------------------------------ geometry
    @staticmethod
    def project(xyz: torch.Tensor, c2w: np.ndarray, fov_x: float, hw: tuple[int, int]):
        h, w = hw
        w2c = torch.from_numpy(np.linalg.inv(c2w)).float().to(xyz.device)
        pc = xyz @ w2c[:3, :3].T + w2c[:3, 3]
        f = 0.5 * w / math.tan(fov_x / 2)
        z = -pc[:, 2]
        u = f * pc[:, 0] / z.clamp(min=1e-6) + w / 2
        v = -f * pc[:, 1] / z.clamp(min=1e-6) + h / 2
        return u, v, z, pc

    def carve(self, view: View) -> int:
        """Apply one view; returns number of voxels still occupied."""
        self.views.append(view)
        h, w = view.image.shape[:2]
        mask = torch.from_numpy(silhouette(view.image)).to(DEVICE)
        self._masks.append(mask)
        u, v, z, _ = self.project(self.xyz, view.c2w, view.fov_x, (h, w))
        inside = (u >= 0) & (u < w) & (v >= 0) & (v < h) & (z > 0)
        ui, vi = u.long().clamp(0, w - 1), v.long().clamp(0, h - 1)
        keep = inside & mask[vi, ui]
        # voxels projecting outside the frame carry no evidence -> keep them
        self.occ &= keep | ~inside
        return int(self.occ.sum())

    def surface(self) -> torch.Tensor:
        """Indices of occupied voxels that touch an empty neighbour."""
        r = self.res
        g = self.occ.reshape(1, 1, r, r, r).float()
        eroded = -F.max_pool3d(-g, 3, 1, 1)
        surf = (g > 0) & (eroded < 1)
        return torch.nonzero(surf.reshape(-1)).squeeze(1)

    def normals(self, idx: torch.Tensor) -> torch.Tensor:
        r = self.res
        g = self.occ.reshape(r, r, r).float()
        g = F.avg_pool3d(g[None, None], 5, 1, 2)[0, 0]
        gz, gy, gx = torch.gradient(g)
        n = -torch.stack([gx, gy, gz], -1).reshape(-1, 3)[idx]
        return F.normalize(n, dim=-1)

    # ------------------------------------------------------------------ appearance
    def colour(self, idx: torch.Tensor, maps: list[np.ndarray] | None = None):
        """Per-surface-point RGB (and optionally per-view scalar maps, e.g. anomaly heat)
        sampled from the most head-on camera that sees the point inside its silhouette."""
        pts = self.xyz[idx]
        nrm = self.normals(idx)
        best = torch.full((len(idx),), -2.0, device=DEVICE)
        rgb = torch.zeros(len(idx), 3, device=DEVICE)
        val = torch.zeros(len(idx), device=DEVICE) if maps is not None else None
        for k, view in enumerate(self.views):
            h, w = view.image.shape[:2]
            u, v, z, _ = self.project(pts, view.c2w, view.fov_x, (h, w))
            cam = torch.from_numpy(view.c2w[:3, 3]).float().to(DEVICE)
            facing = (F.normalize(cam - pts, dim=-1) * nrm).sum(-1)
            ok = (u >= 0) & (u < w) & (v >= 0) & (v < h) & (z > 0)
            ui, vi = u.long().clamp(0, w - 1), v.long().clamp(0, h - 1)
            ok &= self._masks[k][vi, ui]
            better = ok & (facing > best)
            if better.any():
                img = torch.from_numpy(view.image).to(DEVICE)
                rgb[better] = img[vi[better], ui[better]].float() / 255.0
                if maps is not None and maps[k] is not None:
                    m = torch.from_numpy(maps[k]).float().to(DEVICE)
                    mh, mw = m.shape
                    val[better] = m[(vi[better] * mh // h).clamp(0, mh - 1), (ui[better] * mw // w).clamp(0, mw - 1)]
                best = torch.where(better, facing, best)
        return rgb, val, best

    def export(self, max_points: int = 60000, maps: list[np.ndarray] | None = None) -> dict:
        idx = self.surface()
        if len(idx) > max_points:
            idx = idx[torch.randperm(len(idx), device=DEVICE)[:max_points]]
        rgb, val, facing = self.colour(idx, maps)
        nrm = self.normals(idx)
        out = {
            "positions": self.xyz[idx].cpu().numpy().round(4).reshape(-1).tolist(),
            "colors": rgb.cpu().numpy().round(3).reshape(-1).tolist(),
            "normals": nrm.cpu().numpy().round(3).reshape(-1).tolist(),
            "count": int(len(idx)),
            "occupied": int(self.occ.sum()),
            "cameras": [{"position": v.c2w[:3, 3].round(4).tolist(), "matrix": v.c2w.round(4).tolist()} for v in self.views],
            "seen": facing.gt(-2).float().mean().item() if len(idx) else 0.0,
        }
        if val is not None:
            out["heat"] = val.cpu().numpy().round(4).tolist()
        return out

    def coverage(self) -> dict:
        """Which directions around the object have been photographed (for the Curiosity Interview)."""
        dirs = np.stack([v.c2w[:3, 3] / np.linalg.norm(v.c2w[:3, 3]) for v in self.views]) if self.views else np.zeros((0, 3))
        # Fibonacci sphere probes
        n = 200
        i = np.arange(n) + 0.5
        phi = np.arccos(1 - 2 * i / n)
        th = np.pi * (1 + 5 ** 0.5) * i
        probes = np.stack([np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)], -1)
        if len(dirs) == 0:
            return {"covered": 0.0, "gaps": probes[:5].tolist(), "probes": probes.tolist(), "probe_covered": [False] * n}
        cos = probes @ dirs.T
        covered = cos.max(1) > math.cos(math.radians(35))
        return {"covered": float(covered.mean()), "probes": probes.round(3).tolist(),
                "probe_covered": covered.tolist()}


def load_view(path, c2w, fov_x, size: int = 400) -> View:
    im = Image.open(path).convert("RGB").resize((size, size), Image.BILINEAR)
    return View(image=np.asarray(im), c2w=np.asarray(c2w, dtype=np.float64), fov_x=fov_x)
