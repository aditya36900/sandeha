"""How accurate are the defect callouts? Measured on VisA pixel ground truth, products never tuned on.

For every held-out defective test image of each product (the session's own few-shot defect examples excluded):
  - callout precision: share of drawn regions that overlap the true defect (9 px tolerance at 256 px),
  - part recall: share of defective parts with at least one callout on the true defect,
  - top-callout accuracy: the strongest callout sits on the true defect,
  - naming accuracy: the strongest callout's name is one of the image's true defect types
    (fingerprint match against the session's <=5 labelled examples), next to the majority-class baseline,
and the "real-defect odds" per relative-peak bucket that the dashboard shows on each callout.

Writes data/results/regions.json.   usage: python scripts/region_eval.py pcb4 capsules cashew pcb1
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SANDEHA_PERSIST", "0")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from sandeha import regions  # noqa: E402
from sandeha.engine import Session  # noqa: E402

BUCKETS = [(0.7, 0.8), (0.8, 0.9), (0.9, 1.0)]
OUT = Path(__file__).resolve().parents[2] / "data" / "results" / "regions.json"


def run(product: str, seed: int = 0) -> dict:
    s = Session("VisA", product, seed=seed)
    s.genesis()
    known = {id(x) for x in s.known_defects}
    test = [x for x in s.product.test if x.label == 1 and id(x) not in known and x.mask_path is not None]
    lib = s.region_library()
    pol = s.cal.policy
    st = Counter()
    bucket = {b: [0, 0] for b in BUCKETS}
    names, truths = [], []
    t0 = time.time()
    for i in range(0, len(test), 8):
        batch = test[i:i + 8]
        imgs = [x.image() for x in batch]
        g, dist, sc = s.mem.inspect(imgs)
        maps = s.mem.anomaly_maps(dist, g.fg, 256)
        for k, (x, hm) in enumerate(zip(batch, maps)):
            gt = x.mask(256) > 0
            gd = cv2.dilate(gt.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
            cands = regions.candidates(hm, pol.tau_pass)
            top = float(hm.max()) or 1e-9
            hits = [bool((c[0] & gd).any()) for c in cands]
            st["parts"] += 1
            st["callouts"] += len(cands)
            st["correct"] += sum(hits)
            st["partsWithCorrect"] += any(hits)
            st["topCorrect"] += bool(hits) and hits[0]
            st["flagged"] += float(sc[k]) > pol.tau_pass
            for c, h in zip(cands, hits):
                rel = c[3] / top
                for b in BUCKETS:
                    if b[0] <= rel <= b[1] + 1e-9:
                        bucket[b][0] += 1
                        bucket[b][1] += h
                        break
            types = {t.strip() for t in (x.defect_type or "").split(",") if t.strip()}
            if lib and cands and hits[0] and types:
                sig = regions.signature(s.mem, g.feats[k], cands[0][0])
                if sig is not None:
                    names.append(regions.name_by_library(sig, lib)[0])
                    truths.append(types)
    lib_types = Counter(t for t, _ in lib)
    majority = lib_types.most_common(1)[0][0] if lib_types else None
    res = {
        "product": product, "testDefects": st["parts"], "seconds": round(time.time() - t0, 1),
        "calloutPrecision": round(st["correct"] / max(st["callouts"], 1), 3),
        "partRecall": round(st["partsWithCorrect"] / max(st["parts"], 1), 3),
        "topCalloutCorrect": round(st["topCorrect"] / max(st["parts"], 1), 3),
        "calloutsPerPart": round(st["callouts"] / max(st["parts"], 1), 2),
        "namingAccuracy": round(sum(n in t for n, t in zip(names, truths)) / len(names), 3) if names else None,
        "namingBaselineMajority": round(sum(majority in t for t in truths) / len(truths), 3) if truths and majority else None,
        "namedParts": len(names), "libraryTypes": dict(lib_types),
        "buckets": {f"{a}-{b}": v for (a, b), v in bucket.items()},
    }
    print(json.dumps(res), flush=True)
    return res


def main():
    prods = sys.argv[1:] or ["pcb4", "capsules", "cashew", "pcb1"]
    per = [run(p) for p in prods]
    odds = []
    for a, b in BUCKETS:
        n = sum(r["buckets"][f"{a}-{b}"][0] for r in per)
        h = sum(r["buckets"][f"{a}-{b}"][1] for r in per)
        odds.append({"lo": a, "hi": b, "n": n, "precision": round(h / n, 3) if n else None})
    mean = lambda k: round(float(np.mean([r[k] for r in per if r[k] is not None])), 3) if any(r[k] is not None for r in per) else None  # noqa: E731
    out = {"products": per, "odds": odds,
           "mean": {k: mean(k) for k in ("calloutPrecision", "partRecall", "topCalloutCorrect", "calloutsPerPart",
                                         "namingAccuracy", "namingBaselineMajority")},
           "rule": f"candidates > {regions.CAND_REL} x pass line, kept if >= {regions.KEEP_REL} x the part's hottest spot"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("MEAN", json.dumps(out["mean"]), "ODDS", json.dumps(odds))


if __name__ == "__main__":
    main()
