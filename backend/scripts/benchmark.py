"""The honest scoreboard: every held-out VisA test board of each PCB through the whole station, counted.

For each board type (30 good reference photos, 5 known defects used only to set the fail line, seed 0):
  good boards       -> passed / sent to a person / wrongly rejected
  defective boards  -> rejected / sent to a person / wrongly passed
plus the image-level AUROC of the station's score (the number papers report), and what one fixed threshold on the
same score would have done (no "ask a person" band), so the value of the doubt band can be seen separately from the
value of the detector.

Nothing is tuned on the test boards. usage: python scripts/benchmark.py [pcb1 pcb2 pcb3 pcb4]
writes data/results/benchmark.json
"""
from __future__ import annotations

import json
import os
from collections import Counter
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SANDEHA_PERSIST", "0")

import numpy as np  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

from sandeha import data  # noqa: E402
from sandeha.engine import Session  # noqa: E402

OUT = data.DATA_ROOT / "results" / "benchmark.json"


def run(prod: str, stream: bool = False) -> dict:
    s = Session("VisA", prod)
    s.genesis()
    t = time.time()
    while getattr(s, "board", None) is None or not getattr(s, "_board_calibrated", False):
        time.sleep(2)
        if time.time() - t > 900:
            raise RuntimeError("board map / calibration did not finish")
    known = {id(x) for x in s.known_defects}
    test = [x for x in s.product.test if x.label == 0] + [x for x in s.product.test if x.label == 1 and id(x) not in known]
    np.random.default_rng(0).shuffle(test)  # a mixed line, not all the good ones first
    y, sc, dec, naive, lat, patch, why = [], [], [], [], [], [], Counter()
    for x in test:
        if not stream:
            # judge every board on its own. Half of this test set is defective (a real line is a few percent), and
            # run as one stream that looks to the shift guard like a change of conditions, which sends everything to
            # a person. That stream behaviour is reported separately (--stream).
            s.guard.reset(s.global_calib, s.loo)
            s._alarm_announced = False
        r = s.inspect(x.image(), truth=x.label, defect_type=x.defect_type)
        if r.decision == "DOUBT":
            why[r.doubt_reason or "?"] += 1
        y.append(x.label); sc.append(r.score); dec.append(r.decision); naive.append(r.naive_decision); lat.append(r.latency_ms)
        patch.append((r.signals or {}).get("patchMemory", r.score))
    y, sc, dec, naive, patch = np.array(y), np.array(sc), np.array(dec), np.array(naive), np.array(patch)
    g, b = y == 0, y == 1
    cnt = lambda m, d: int((m & (dec == d)).sum())
    good = {"total": int(g.sum()), "passed": cnt(g, "PASS"), "askedPerson": cnt(g, "DOUBT"), "wronglyRejected": cnt(g, "FAIL"), "held": cnt(g, "HOLD")}
    bad = {"total": int(b.sum()), "rejected": cnt(b, "FAIL"), "askedPerson": cnt(b, "DOUBT"), "wronglyPassed": cnt(b, "PASS"), "held": cnt(b, "HOLD")}
    n = len(y)
    auto_right = good["passed"] + bad["rejected"]
    wrong = good["wronglyRejected"] + bad["wronglyPassed"]
    asked = good["askedPerson"] + bad["askedPerson"] + good["held"] + bad["held"]
    # one fixed threshold on the same score, placed where it makes the fewest mistakes ON THE TEST SET (an oracle:
    # the best any single threshold could do; a real one, set in advance, does worse)
    thr = np.unique(sc)
    errs = [(int(((sc > t) & g).sum() + ((sc <= t) & b).sum()), float(t)) for t in thr]
    best_err, best_t = min(errs)
    out = {"product": prod, "mode": "one stream" if stream else "each board on its own", "askedWhy": dict(why), "boards": n, "good": good, "defective": bad,
           "decidedAloneAndRight": auto_right, "wrong": wrong, "sentToPerson": asked,
           "rightShare": round(auto_right / n, 4), "wrongShare": round(wrong / n, 4), "personShare": round(asked / n, 4),
           "aurocStation": round(float(roc_auc_score(y, sc)), 4), "aurocPatchMemoryOnly": round(float(roc_auc_score(y, patch)), 4),
           "singleThreshold": {"stationPreset": {"wronglyPassed": int((b & (naive == "PASS")).sum()), "wronglyRejected": int((g & (naive == "FAIL")).sum())},
                               "bestPossible": {"wrong": best_err, "note": "threshold chosen with hindsight on these test boards"}},
           "latencyMsP50": round(float(np.median(lat[5:])), 1), "references": len(s.ref_images), "knownDefects": len(s.known_defects),
           "passLine": round(float(s.cal.policy.tau_pass), 4), "failLine": round(float(s.cal.policy.tau_fail), 4)}
    print(json.dumps(out), flush=True)
    return out


if __name__ == "__main__":
    res = json.loads(OUT.read_text()) if OUT.exists() else {"products": {}}
    stream = "--stream" in sys.argv
    for p in [a for a in sys.argv[1:] if not a.startswith("--")] or ["pcb1", "pcb2", "pcb3", "pcb4"]:
        res.setdefault("stream" if stream else "products", {})[p] = run(p, stream)
        OUT.write_text(json.dumps(res, indent=1))
