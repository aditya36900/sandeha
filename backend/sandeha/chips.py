"""Chip identity check: read the marking printed on every IC and compare it with the golden board.

A wrong, missing, re-marked or counterfeit chip often still looks like 'an IC' to an anomaly detector, but its
marking differs. The local vision-language model (Qwen2-VL-2B) reads the text (reading printed text is its strong
suit, unlike judging defects); the comparison is plain string similarity, so the verdict is measurable.
"""
from __future__ import annotations

import difflib
import re

import numpy as np
from PIL import Image

from .board import align, to_work

PROMPT = ("Read the text printed on top of this electronic chip exactly as written, characters only. "
          "If there is no readable text, answer NONE.")
CHIP_KINDS = ("IC", "transistor")


def _norm(t: str) -> str:
    t = t.upper().replace("O", "0").replace("I", "1").replace("L", "1")  # common OCR look-alikes
    return re.sub(r"[^A-Z0-9]", "", t)


def similarity(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _crop(img: np.ndarray, bbox, pad: float = 0.12) -> Image.Image:
    x, y, w, h = bbox
    p = int(pad * max(w, h))
    H, W = img.shape[:2]
    c = img[max(0, y - p):min(H, y + h + p), max(0, x - p):min(W, x + w + p)]
    im = Image.fromarray(c)
    s = 448 / max(im.size)
    return im.resize((max(28, int(im.width * s)), max(28, int(im.height * s))), Image.BICUBIC)


def read(crop: Image.Image) -> str:
    from . import vlm

    t = vlm.generate([crop], PROMPT, 24).strip().split("\n")[0]
    return "" if t.upper().startswith("NONE") else t


def golden_markings(s) -> dict:
    cache = getattr(s, "_golden_marks", None)
    if cache is not None:
        return cache
    from collections import Counter

    bm = s.board
    # the median golden image is slightly soft; read the sharp reference photos and take the majority
    refs = [align(to_work(im), bm.golden)[0] for im in s.ref_images[:3]]
    out = {}
    for c in bm.components:
        if c.kind in CHIP_KINDS and c.area > 300:
            reads = [read(_crop(a, c.bbox)) for a in refs]
            out[c.id] = Counter(reads).most_common(1)[0][0]
    s._golden_marks = out
    return out


def check(s, rid: str) -> dict:
    from . import vlm

    cache = getattr(s, "_chip_checks", None)
    if cache is None:
        s._chip_checks = cache = {}
    if rid in cache:
        return cache[rid]
    bm = getattr(s, "board", None)
    if bm is None or not vlm.available():
        return {"available": False, "chips": []}
    r = next((x for x in s.records if x.id == rid), None)
    if r is None:
        raise KeyError(rid)
    from .visual import MEDIA

    from .visual import load_media

    crops = (r.board or {}).get("chipCrops") or {}
    a = None
    if not crops:  # older scans: fall back to the stored (lower-resolution) photo
        img = Image.open(MEDIA / r.image_url.replace("/media/", "", 1)).convert("RGB")
        a, _ = align(to_work(img), bm.golden)
    gold = golden_markings(s)
    chips = []
    for cid, expected in gold.items():
        c = next(x for x in bm.components if x.id == cid)
        crop = load_media(crops[cid]) if cid in crops else None
        got = read(crop if crop is not None else _crop(a if a is not None else align(to_work(Image.open(MEDIA / r.image_url.replace("/media/", "", 1)).convert("RGB")), bm.golden)[0], c.bbox))
        sim = similarity(expected, got)
        if not expected:
            verdict = "no marking on the golden chip"
        elif not got:
            verdict = "MARKING UNREADABLE"
        elif sim >= 0.75:
            verdict = "MATCH"
        elif sim >= 0.45:
            verdict = "PARTIAL"
        else:
            verdict = "DIFFERENT"
        chips.append({"id": cid, "kind": c.kind, "expected": expected, "read": got, "similarity": round(sim, 2), "verdict": verdict,
                      "crop": crops.get(cid), "lowRes": cid not in crops,
                      "bbox": [c.bbox[0] / bm.golden.shape[1], c.bbox[1] / bm.golden.shape[0], c.bbox[2] / bm.golden.shape[1], c.bbox[3] / bm.golden.shape[0]]})
    out = {"available": True, "chips": chips, "model": vlm.MODEL,
           "note": "Markings read by the local VLM and compared character by character with the golden board. "
                   "A DIFFERENT or unreadable marking means: verify the part (wrong reel, re-marked or counterfeit chip, or a burnt top)."}
    cache[rid] = out
    return out
