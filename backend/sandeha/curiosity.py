"""The Curiosity Interview: before trusting its references, the AI asks questions about them.

Questions are generated from evidence, never canned:
  1. SUSPECT REFERENCE  - a "good" photo is unlike the others (leave-one-out outlier) -> possibly
                          a defective part hiding in the training set (silent poisoning).
  2. VARIATION ZONE     - a region varies a lot between good photos -> is that variation acceptable?
  3. COVERAGE GAP       - (posed products) directions around the object never photographed.
  4. SUFFICIENCY        - is the calibration still moving? how many more photos would stabilise it?
  5. CRITICAL ZONES     - asks the human to paint zones where defects matter most.
"""
from __future__ import annotations

import io
import base64

import numpy as np
from PIL import Image

from .trust import conformal_upper


def _b64(img: Image.Image, size: int = 256) -> str:
    buf = io.BytesIO()
    img.convert("RGB").resize((size, size)).save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _overlay(img: Image.Image, heat: np.ndarray, size: int = 256) -> Image.Image:
    base = np.asarray(img.convert("RGB").resize((size, size))).astype(np.float32) / 255
    h = np.asarray(Image.fromarray((np.clip(heat, 0, 1) * 255).astype(np.uint8)).resize((size, size), Image.BILINEAR)) / 255.0
    col = np.stack([h, 0.35 * h, 0.1 * h], -1)
    a = np.clip(h * 1.2, 0, 0.75)[..., None]
    return Image.fromarray(((base * (1 - a) + col * a) * 255).astype(np.uint8))


def suspect_references(loo: np.ndarray, maps: np.ndarray, refs: list[Image.Image], z_thr: float = 3.5) -> list[dict]:
    med = float(np.median(loo))
    mad = float(np.median(np.abs(loo - med))) * 1.4826 + 1e-9
    z = (loo - med) / mad
    out = []
    for i in np.argsort(-z)[:3]:
        if z[i] < z_thr:
            break
        m = maps[i] / (maps[i].max() + 1e-9)
        out.append({
            "type": "SUSPECT_REFERENCE", "refIndex": int(i), "zScore": round(float(z[i]), 2),
            "question": f"Photo #{i + 1} doesn't look like the other good photos "
                        f"({z[i]:.1f} robust standard deviations away). Is this part really good?",
            "why": "If a defective part hides in the 'good' set, the AI learns to accept that defect forever.",
            "image": _b64(_overlay(refs[i], m)),
            "options": ["It's good, keep it", "It's defective, remove it"],
        })
    return out


def _zone(shape, y, x, r) -> np.ndarray:
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    return np.exp(-(((yy - y) ** 2 + (xx - x) ** 2) / (2 * (1.2 * r) ** 2)))


def variation_zones(maps: np.ndarray, refs: list[Image.Image], top: int = 2) -> list[dict]:
    """For pose-aligned products: where do good parts disagree with each other the most?"""
    var = maps.mean(0)
    flat = np.sort(var.ravel())
    # only ask when variation is concentrated in a zone (aligned parts); diffuse variation
    # (randomly placed items like capsules) has no zone worth asking about
    concentration = flat[-max(1, len(flat) // 50):].mean() / (flat.mean() + 1e-9)
    if concentration < 2.4:  # measured: random layouts (capsules 1.6) vs aligned parts (candle 2.6, pcb4 3.0)
        return []
    var = var / (var.max() + 1e-9)
    h, w = var.shape
    out = []
    taken = np.zeros_like(var, bool)
    for _ in range(top):
        v = np.where(taken, -1, var)
        y, x = np.unravel_index(int(np.argmax(v)), v.shape)
        if v[y, x] < 0.5:
            break
        r = max(h // 10, 8)
        taken[max(0, y - 2 * r):y + 2 * r, max(0, x - 2 * r):x + 2 * r] = True
        crops = []
        order = np.argsort(-maps[:, y, x])[:3]
        for j in order:
            im = refs[j].convert("RGB").resize((w, h))
            crops.append(_b64(im.crop((max(0, x - 2 * r), max(0, y - 2 * r), min(w, x + 2 * r), min(h, y + 2 * r))), 128))
        out.append({
            "type": "VARIATION_ZONE", "x": round(100 * x / w, 1), "y": round(100 * y / h, 1),
            "question": "Good parts vary a lot here. Is this kind of variation acceptable, "
                        "or should I be stricter in this zone?",
            "why": "Natural variation in a zone hides small defects there; telling me which variation is fine "
                   "lets me tighten everywhere else.",
            "image": _b64(_overlay(refs[0], _zone(var.shape, y, x, r))), "crops": crops,
            "options": ["Acceptable variation", "Be stricter here"],
        })
    return out


def sufficiency(loo: np.ndarray, alpha: float = 0.02, rng=None) -> dict:
    """How much does the calibrated threshold still move as photos are added? (bootstrap)"""
    rng = rng or np.random.default_rng(0)
    n = len(loo)
    sizes = [k for k in (10, 15, 20, 25, 30, 40) if k <= n]
    curve = []
    for k in sizes:
        taus = [conformal_upper(rng.choice(loo, k, replace=True), alpha) for _ in range(200)]
        curve.append({"n": k, "tau": float(np.mean(taus)), "spread": float(np.std(taus) / (np.mean(taus) + 1e-9))})
    spread = curve[-1]["spread"] if curve else 1.0
    need = 0
    if spread > 0.05 and len(curve) >= 2:  # extrapolate ~1/sqrt(n) shrinkage to 5% spread
        need = int(np.ceil(n * (spread / 0.05) ** 2 - n))
    q = None
    if need > 0:
        q = {"type": "SUFFICIENCY", "question": f"My pass/fail line still wobbles by ±{spread:.0%}. "
                                               f"About {need} more good photos would make it stable. Can you add some?",
             "why": "With too few references the guarantee holds but the line is loose, so more parts go to review.",
             "options": ["Add photos", "Continue with what we have"]}
    return {"curve": curve, "spread": spread, "morePhotosNeeded": need, "question": q}


def coverage_gaps(coverage: dict, pool_dirs: np.ndarray | None = None, used: set[int] | None = None) -> list[dict]:
    probes = np.array(coverage["probes"])
    covered = np.array(coverage["probe_covered"])
    if covered.all() or not len(probes):
        return []
    gaps = probes[~covered]
    centroid = gaps.mean(0)
    centroid /= np.linalg.norm(centroid) + 1e-9
    elev = float(np.degrees(np.arcsin(np.clip(centroid[2], -1, 1))))
    where = "underneath" if elev < -30 else "from above" if elev > 30 else "from the side"
    q = {"type": "COVERAGE_GAP", "direction": centroid.round(3).tolist(), "uncovered": round(1 - float(covered.mean()), 3),
         "question": f"I've never seen this part {where} ({(1 - covered.mean()):.0%} of directions unseen). "
                     f"A defect there would be invisible to me. Can you show me that side?",
         "why": "The AI cannot vouch for surfaces it has never seen; it will send parts showing that side to review.",
         "options": ["Add photo from that side", "That side doesn't matter"]}
    if pool_dirs is not None:
        cand = [i for i in range(len(pool_dirs)) if not used or i not in used]
        if cand:
            gains = [(gaps @ pool_dirs[i] > np.cos(np.radians(35))).sum() for i in cand]
            q["suggestedView"] = int(cand[int(np.argmax(gains))])
    return [q]


def critical_zone_prompt() -> dict:
    return {"type": "CRITICAL_ZONES",
            "question": "Paint the zones where a defect would be unacceptable (e.g. sealing faces, threads, contacts). "
                        "I'll be strictest there and more tolerant elsewhere.",
            "why": "Not every millimetre matters equally; this turns your expertise into the inspection policy.",
            "options": ["Paint zones", "Treat all zones equally"]}


def interview(loo: np.ndarray, maps: np.ndarray, refs: list[Image.Image], aligned: bool,
              coverage: dict | None = None, pool_dirs=None, used=None) -> dict:
    qs = suspect_references(loo, maps, refs)
    if aligned:
        qs += variation_zones(maps, refs)
    if coverage is not None:
        qs += coverage_gaps(coverage, pool_dirs, used)
    suff = sufficiency(loo)
    if suff["question"]:
        qs.append(suff["question"])
    if aligned:  # painted zones are image coordinates: only meaningful for fixed-camera products
        qs.append(critical_zone_prompt())
    for i, q in enumerate(qs):
        q["id"] = f"Q{i + 1}"
    return {"questions": qs, "sufficiency": suff}
