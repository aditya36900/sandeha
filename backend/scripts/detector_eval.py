"""Measure the whole inspection path (as the station runs it) under a given configuration.

Settings come from the environment, so one script measures everything:
  SANDEHA_GOLDEN_GAIN=0      python scripts/detector_eval.py pcb4   # patch memory only
  SANDEHA_GOLDEN_GAIN=0.02   python scripts/detector_eval.py pcb4   # fused with the golden-board deviation
  SANDEHA_PROFILE=edge       python scripts/detector_eval.py pcb4   # INT8 ONNX on CPU + 10% coreset
  SANDEHA_CORESET=0.1        python scripts/detector_eval.py pcb4   # GPU with compact memory

Reports AUROC, false rejects on good boards, escapes, review rate, and inspect latency (p50) on held-out boards.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SANDEHA_PERSIST", "0")

import numpy as np  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

from sandeha.engine import CORESET, GOLDEN_GAIN, Session  # noqa: E402
from sandeha.backbone import DEVICE, EDGE  # noqa: E402


def run(prod: str, n_good: int = 80, n_bad: int = 80) -> dict:
    s = Session("VisA", prod)
    s.genesis()
    t = time.time()
    while getattr(s, "board", None) is None or not getattr(s, "_board_calibrated", False):
        time.sleep(2)
        if time.time() - t > 900:
            raise RuntimeError("board map / calibration did not finish")
    known = {id(x) for x in s.known_defects}
    test = [x for x in s.product.test if x.label == 0][:n_good] + [x for x in s.product.test if x.label == 1 and id(x) not in known][:n_bad]
    y, sc, dec, lat = [], [], [], []
    for x in test:
        r = s.inspect(x.image(), truth=x.label, defect_type=x.defect_type)
        y.append(x.label); sc.append(r.score); dec.append(r.decision); lat.append(r.latency_ms)
    y, sc, dec = np.array(y), np.array(sc), np.array(dec)
    pol = s.cal.policy
    out = {"product": prod, "profile": "edge" if EDGE else "full", "device": DEVICE, "goldenGain": GOLDEN_GAIN,
           "coreset": getattr(s, "memory_info", None), "patches": int(len(s.mem.bank)),
           "auroc": round(float(roc_auc_score(y, sc)), 4),
           "falseRejectsOnGood": round(float(((dec == "FAIL") & (y == 0)).mean() * len(y) / max(1, (y == 0).sum())), 3),
           "escapes": round(float(((dec == "PASS") & (y == 1)).sum() / max(1, (y == 1).sum())), 3),
           "reviewRate": round(float((dec == "DOUBT").mean()), 3),
           "latencyMsP50": round(float(np.median(lat[5:])), 1), "passLine": round(float(pol.tau_pass), 4), "failLine": round(float(pol.tau_fail), 4),
           "calibratedOn": getattr(s, "calibrated_on", None)}
    print(json.dumps(out), flush=True)
    return out


if __name__ == "__main__":
    for p in sys.argv[1:] or ["pcb4"]:
        run(p)
