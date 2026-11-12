"""Defect regions: turn an anomaly map into separate, measured, named defects.

For every flagged part:
  1. candidate regions = connected areas of the patch-distance map above 0.85 x the calibrated pass line,
  2. keep a region only if it reaches >= 70% of the part's own hottest spot. Measured on VisA pcb4 against
     pixel ground truth (scripts/region_eval.py): precision 0.44 -> 0.66 while 91% of defective parts
     still get a callout on the real defect,
  3. name each region by its deviation fingerprint (the direction its patches move away from the nearest normal
     patches), matched against this product's own labelled defect examples; CLIP zero-shot
     (openai/clip-vit-base-patch16, runs locally) only when there are no labelled examples,
  4. grade severity from how far its peak sits beyond the calibrated lines,
  5. attach the measured odds that a region like this is a real defect (from data/results/regions.json).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image

KEEP_REL = 0.7
CAND_REL = 0.85
CLIP_MODEL = "openai/clip-vit-base-patch16"
LABELS = [
    ("scratch", "a close-up photo of a scratch on a manufactured part"),
    ("crack", "a close-up photo of a crack in a manufactured part"),
    ("stain", "a close-up photo of a stain or discoloration on a manufactured part"),
    ("dent / deformation", "a close-up photo of a dent or bent, deformed area on a manufactured part"),
    ("missing piece / chip", "a close-up photo of a chipped part with a missing piece"),
    ("burr / excess material", "a close-up photo of a burr or excess material on a manufactured part"),
    ("contamination", "a close-up photo of dirt, dust, hair or a foreign object on a manufactured part"),
    ("hole / pore", "a close-up photo of a hole, pit or pore in a surface"),
    ("normal surface", "a close-up photo of a clean, normal, defect-free surface"),
]
RESULTS = Path(__file__).resolve().parents[2] / "data" / "results" / "regions.json"

_CLIP = None
_LOCK = threading.Lock()


def _vec(out):
    """transformers 4 returns a tensor, transformers 5 an output object holding the projected embedding."""
    if torch.is_tensor(out):
        return out
    return out.pooler_output if getattr(out, "pooler_output", None) is not None else out[0]


def _clip():
    global _CLIP
    with _LOCK:
        if _CLIP is None:
            from transformers import CLIPModel, CLIPProcessor

            dev = "cuda" if torch.cuda.is_available() else "cpu"
            model = CLIPModel.from_pretrained(CLIP_MODEL, torch_dtype=torch.float16 if dev == "cuda" else torch.float32).to(dev).eval()
            proc = CLIPProcessor.from_pretrained(CLIP_MODEL)
            with torch.no_grad():
                t = proc(text=[p for _, p in LABELS], return_tensors="pt", padding=True).to(dev)
                tf = torch.nn.functional.normalize(_vec(model.get_text_features(**t)).float(), dim=-1)
            _CLIP = (model, proc, tf, dev)
        return _CLIP


def clip_names(crops: list[Image.Image]) -> list[list[tuple[str, float]]]:
    """Top-3 (label, probability) for each crop."""
    if not crops:
        return []
    model, proc, tf, dev = _clip()
    with torch.no_grad():
        px = proc(images=crops, return_tensors="pt")["pixel_values"].to(dev)
        if dev == "cuda":
            px = px.half()
        im = torch.nn.functional.normalize(_vec(model.get_image_features(pixel_values=px)).float(), dim=-1)
        prob = (100 * im @ tf.T).softmax(-1).cpu().numpy()
    out = []
    for p in prob:
        order = np.argsort(-p)[:3]
        out.append([(LABELS[i][0], float(p[i])) for i in order])
    return out


_ODDS = None


def odds_table() -> list[dict] | None:
    """Measured P(real defect | region's relative-peak bucket), written by scripts/region_eval.py."""
    global _ODDS
    if _ODDS is None:
        try:
            _ODDS = json.loads(RESULTS.read_text(encoding="utf-8"))
        except Exception:
            _ODDS = {}
    return _ODDS.get("odds")


def _odds(rel: float) -> float | None:
    for b in odds_table() or []:
        if b["lo"] <= rel <= b["hi"] + 1e-9:
            return b["precision"]
    return None


def candidates(heat: np.ndarray, tau_pass: float, keep_rel: float = KEEP_REL, max_regions: int = 4):
    """Connected regions worth a callout: (mask256, stats, centroid, peak) sorted by peak."""
    m = cv2.morphologyEx((heat > CAND_REL * tau_pass).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, st, cent = cv2.connectedComponentsWithStats(m, 8)
    top = float(heat.max()) or 1e-9
    out = []
    for k in range(1, n):
        if st[k, cv2.CC_STAT_AREA] < 12:
            continue
        cm = lab == k
        peak = float(heat[cm].max())
        if peak < keep_rel * top:
            continue
        out.append((cm, st[k], cent[k], peak))
    out.sort(key=lambda r: -r[3])
    return out[:max_regions]


@torch.no_grad()
def signature(mem, feats: torch.Tensor, mask256: np.ndarray) -> torch.Tensor | None:
    """Deviation fingerprint of one region: mean direction its patches move away from their nearest normal patch.
    feats: (P, D) patch features of the inspected image on the memory's patch grid."""
    h, w = mem.hw
    pm = cv2.resize(mask256.astype(np.float32), (w, h), interpolation=cv2.INTER_AREA) > 0.05
    idx = torch.from_numpy(np.flatnonzero(pm.reshape(-1))).to(feats.device)
    if idx.numel() == 0:
        return None
    q = feats[idx]
    bank = mem.bank
    sims = (q.half() if bank.dtype == torch.float16 else q) @ bank.T
    nn = bank[sims.argmax(1)].float()
    r = torch.nn.functional.normalize(q.float() - nn, dim=-1).mean(0)
    return torch.nn.functional.normalize(r, dim=0)


def name_by_library(sig: torch.Tensor, lib: list) -> tuple[str, float, list]:
    L = torch.stack([s for _, s in lib]).to(sig.device)
    sim = (L @ sig).cpu().numpy()
    best: dict = {}
    for (t, _), v in zip(lib, sim):
        best[t] = max(best.get(t, -1.0), float(v))
    ranked = sorted(best.items(), key=lambda kv: -kv[1])
    return ranked[0][0], ranked[0][1], ranked[1:3]


def find_regions(heat: np.ndarray, img: Image.Image, fg: np.ndarray | None, tau_pass: float, tau_fail: float,
                 mem=None, feats: torch.Tensor | None = None, library: list | None = None,
                 max_regions: int = 4) -> list[dict]:
    """heat: (256, 256) patch-distance map aligned with img; library: [(type_name, signature)] from labelled
    defect examples of this product."""
    h, w = heat.shape
    part_area = float(fg.sum()) if fg is not None and fg.sum() > 0 else float(h * w)
    top = float(heat.max()) or 1e-9
    W, H = img.size
    regs, crops, sigs = [], [], []
    for i, (cm, st, cent, peak) in enumerate(candidates(heat, tau_pass, max_regions=max_regions)):
        x, y, bw, bh, area = (int(v) for v in st)
        r = {"id": f"R{i + 1}", "bbox": [x / w, y / h, bw / w, bh / h], "centroid": [float(cent[0]) / w, float(cent[1]) / h],
             "areaPct": round(100 * area / part_area, 2), "peak": round(peak, 4), "extentPct": round(100 * max(bw, bh) / w, 1),
             "relPeak": round(peak / top, 3), "unusualness": round(peak / max(tau_pass, 1e-9), 2)}
        ratio = peak / max(tau_fail, 1e-9)
        r["severity"] = "critical" if ratio > 1.6 else "major" if ratio > 1.0 else "minor"
        r["realOdds"] = _odds(r["relPeak"])
        bx, by, bw_, bh_ = r["bbox"]
        pad = max(bw_, bh_) * 0.6 + 0.04
        box = (max(0, (bx - pad) * W), max(0, (by - pad) * H), min(W, (bx + bw_ + pad) * W), min(H, (by + bh_ + pad) * H))
        crops.append(img.crop(tuple(int(v) for v in box)).resize((224, 224)))
        sigs.append(signature(mem, feats, cm) if mem is not None and feats is not None else None)
        r["_mask"] = cm
        regs.append(r)
    lib = [(t, s) for t, s in (library or []) if s is not None]
    clip = None
    for i, r in enumerate(regs):
        r["_crop"] = crops[i]
        if lib and sigs[i] is not None:
            label, simv, alts = name_by_library(sigs[i], lib)
            r["label"], r["similarity"] = label, round(simv, 3)
            r["namedBy"] = "closest labelled defect of this product"
            r["alternatives"] = [{"label": t, "similarity": round(v, 3)} for t, v in alts]
        else:
            if clip is None:
                try:
                    clip = clip_names(crops)
                except Exception:
                    clip = [[("unusual area", 0.0)]] * len(crops)
            nm = clip[i]
            top_ = nm[0]
            if top_[0] == "normal surface" and len(nm) > 1:  # CLIP sees nothing typical: still unusual vs memory
                top_ = (nm[1][0] if nm[1][1] > 0.15 else "unusual texture", nm[1][1])
            r["label"], r["similarity"] = top_[0], round(top_[1], 3)
            r["namedBy"] = "CLIP zero-shot (no labelled examples)"
            r["alternatives"] = [{"label": a, "similarity": round(p, 3)} for a, p in nm if a != top_[0]][:2]
    return regs
