"""Component-level inspection accuracy on electronics (VisA pcb1-pcb4).

Real defects: every held-out defective test board. The true defect pixels (VisA mask) are carried into the
golden-board frame; a board counts as localised if a component overlapping the defect is flagged (or an EXTRA
region overlaps it). Diagnosis is scored against VisA's own type labels with a lenient mapping:
missing -> MISSING; wrong place -> SHIFTED/ROTATED/WRONG_PART; burnt / melt -> BURNT/DAMAGED;
extra -> EXTRA/WRONG_PART/DAMAGED; bent -> SHIFTED/DAMAGED/WRONG_PART; others (damage, dirt, scratch) -> any.
Good boards: flagged components per held-out good board (false alarms).
Synthetic: each fault kind planted on one random component of held-out good boards (known truth).

usage: python scripts/board_eval.py pcb4 pcb3 pcb2 pcb1   -> data/results/board.json
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SANDEHA_PERSIST", "0")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from sandeha.board import EXPECT, FAULTS, BoardMap, align, plant_fault, to_work  # noqa: E402
from sandeha.engine import Session  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "data" / "results" / "board.json"
REAL = {"missing": {"MISSING"}, "wrong place": {"SHIFTED", "ROTATED", "WRONG_PART"}, "burnt": {"BURNT", "DAMAGED"},
        "melt": {"BURNT", "DAMAGED"}, "extra": {"EXTRA", "WRONG_PART", "DAMAGED"}, "bent": {"SHIFTED", "DAMAGED", "WRONG_PART"}}


def heat_of(s, img):
    g, dist, sc = s.mem.inspect([img])
    return s.mem.anomaly_maps(dist, g.fg, 256)[0], float(sc[0])


def run(prod: str, n_good: int = 25, n_syn: int = 12, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    s = Session("VisA", prod, seed=seed)
    s.genesis()
    t0 = time.time()
    calib = []
    for x in s.spare_good[:40]:  # never references, never tested
        im = x.image()
        calib.append((im, heat_of(s, im)[0]))
    bm = BoardMap.build(s.ref_images, list(s.loo_maps), calib)
    build_s = time.time() - t0
    tp = s.cal.policy.tau_pass
    known = {id(x) for x in s.known_defects}
    test_bad = [x for x in s.product.test if x.label == 1 and id(x) not in known and x.mask_path is not None]
    test_good = [x for x in s.product.test if x.label == 0][:n_good]
    res = {"product": prod, "calibration": bm.calibration, "components": len(bm.components), "kinds": dict(Counter(c.kind for c in bm.components)),
           "buildSeconds": round(build_s, 1)}
    # ---- good boards: false alarms
    fa = []
    for x in test_good:
        img = x.image()
        hm, _ = heat_of(s, img)
        d = bm.diagnose(img, hm, tp)
        fa.append(d["faults"])
    res["good"] = {"boards": len(fa), "flaggedPerBoard": round(float(np.mean(fa)), 2), "boardsWithAnyFlag": round(float(np.mean([f > 0 for f in fa])), 3)}
    # ---- real defects
    loc, diag, n = 0, Counter(), Counter()
    for x in test_bad:
        img = x.image()
        hm, _ = heat_of(s, img)
        d = bm.diagnose(img, hm, tp)
        work = to_work(img)
        _, warp = align(work, bm.golden)
        gt = (x.mask() > 0).astype(np.float32)
        H, W = bm.golden.shape[:2]
        gtw = cv2.warpAffine(cv2.resize(gt, (work.shape[1], work.shape[0])), warp, (W, H), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP) > 0.5
        gtd = cv2.dilate(gtw.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
        hit_status = []
        for r in d["components"]:
            c = next(c for c in bm.components if c.id == r["id"])
            if r["status"] != "OK" and (c.mask & gtd).any():
                hit_status.append(r["status"])
        for e in d["extra"]:
            bx, by, bw, bh = e["bbox"]
            if gtd[int(by * H):int((by + bh) * H) + 1, int(bx * W):int((bx + bw) * W) + 1].any():
                hit_status.append("EXTRA")
        loc += bool(hit_status)
        for t in {t.strip() for t in (x.defect_type or "").split(",") if t.strip()}:
            n[t] += 1
            if hit_status and (t not in REAL or set(hit_status) & REAL[t]):
                diag[t] += 1
    res["real"] = {"boards": len(test_bad), "localised": round(loc / max(len(test_bad), 1), 3),
                   "diagnosedByType": {t: {"n": n[t], "right": diag[t], "rate": round(diag[t] / n[t], 3)} for t in sorted(n)}}
    # ---- synthetic faults with known truth
    cands = [c for c in bm.components if c.kind not in ("hole / pad",)]
    syn = defaultdict(lambda: {"n": 0, "flagged": 0, "diagnosed": 0, "otherFlags": 0})
    for kind in FAULTS:
        for j in range(n_syn):
            x = test_good[(j * 3 + FAULTS.index(kind)) % len(test_good)]
            pool = [c for c in cands if c.kind in ("IC", "diode / LED", "transistor", "other")] if kind == "rotated" else cands
            c = (pool or cands)[int(rng.integers(len(pool or cands)))]
            img = plant_fault(x.image(), bm, c.id, kind, rng)
            hm, _ = heat_of(s, img)
            d = bm.diagnose(img, hm, tp)
            st = next(r["status"] for r in d["components"] if r["id"] == c.id)
            k = syn[kind]
            k["n"] += 1
            k["flagged"] += st != "OK"
            k["diagnosed"] += st in EXPECT[kind]
            k["otherFlags"] += sum(r["status"] != "OK" for r in d["components"] if r["id"] != c.id)
    res["synthetic"] = {k: {**v, "flaggedRate": round(v["flagged"] / v["n"], 3), "diagnosedRate": round(v["diagnosed"] / v["n"], 3)} for k, v in syn.items()}
    print(json.dumps(res), flush=True)
    return res


def main():
    per = [run(p) for p in (sys.argv[1:] or ["pcb4", "pcb3", "pcb2", "pcb1"])]
    agg_syn = {}
    for kind in FAULTS:
        n = sum(r["synthetic"][kind]["n"] for r in per)
        agg_syn[kind] = {"n": n, "flaggedRate": round(sum(r["synthetic"][kind]["flagged"] for r in per) / n, 3),
                         "diagnosedRate": round(sum(r["synthetic"][kind]["diagnosed"] for r in per) / n, 3)}
    real_types = defaultdict(lambda: [0, 0])
    for r in per:
        for t, v in r["real"]["diagnosedByType"].items():
            real_types[t][0] += v["n"]
            real_types[t][1] += v["right"]
    out = {"products": per,
           "summary": {"localisedReal": round(float(np.mean([r["real"]["localised"] for r in per])), 3),
                       "goodFlagsPerBoard": round(float(np.mean([r["good"]["flaggedPerBoard"] for r in per])), 2),
                       "goodBoardsWithAnyFlag": round(float(np.mean([r["good"]["boardsWithAnyFlag"] for r in per])), 3),
                       "realByType": {t: {"n": v[0], "rate": round(v[1] / v[0], 3)} for t, v in sorted(real_types.items())},
                       "synthetic": agg_syn}}
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("SUMMARY", json.dumps(out["summary"]))


if __name__ == "__main__":
    main()
