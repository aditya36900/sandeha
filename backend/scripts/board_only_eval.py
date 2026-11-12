"""Does scoring only the board (not the mat around it) make verdicts and callouts more accurate?

Same held-out VisA test boards, scored twice: whole-photo foreground (before) vs board-only (after), each with its own
leave-one-out calibration. Reports AUROC, false rejects on good boards, escapes, review rate, and the share of region
callouts that fall outside the board.

usage: python scripts/board_only_eval.py pcb4
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SANDEHA_PERSIST", "0")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

from sandeha import regions  # noqa: E402
from sandeha.board import align, to_work  # noqa: E402
from sandeha.engine import Session  # noqa: E402


def run(prod: str, n_good: int = 80, n_bad: int = 80):
    s = Session("VisA", prod)
    s.genesis()
    while getattr(s, "board", None) is None or not getattr(s, "_board_calibrated", False):
        time.sleep(2)  # component map + board-only recalibration run in the background
    known = {id(x) for x in s.known_defects}
    test = [x for x in s.product.test if x.label == 0][:n_good] + [x for x in s.product.test if x.label == 1 and id(x) not in known][:n_bad]
    imgs = [x.image() for x in test]
    y = np.array([x.label for x in test])
    bm = s.board
    out = {"product": prod, "good": int((y == 0).sum()), "defective": int((y == 1).sum())}
    for mode in ("before", "after"):
        s._board_calibrated = mode == "after"
        with s.lock:
            s._recalibrate_zones() if mode == "before" else s._board_recalibrate()
        pol = s.cal.policy
        scores, off = [], [0, 0]
        for i in range(0, len(imgs), 8):
            b = imgs[i:i + 8]
            g, dist, _ = s.mem.inspect(b)
            fg = s._board_fg(b, g)
            sc = s._weighted_score(dist, fg).cpu().numpy()
            scores += sc.tolist()
            maps = s.mem.anomaly_maps(dist, fg, 256)
            for im, hm in zip(b, maps):  # callouts outside the board outline
                work = to_work(im)
                _, warp = align(work, bm.golden)
                H, W = work.shape[:2]
                m = cv2.warpAffine(bm.board.astype(np.uint8), warp, (W, H), flags=cv2.INTER_NEAREST)
                m = cv2.resize(m, (256, 256), interpolation=cv2.INTER_NEAREST) > 0
                for cm, *_ in regions.candidates(hm, pol.tau_pass):
                    off[0] += 1
                    off[1] += (cm & m).sum() < 0.5 * cm.sum()
        scores = np.array(scores)
        dec = np.where(scores > pol.tau_fail, "FAIL", np.where(scores > pol.tau_pass, "DOUBT", "PASS"))
        out[mode] = {"auroc": round(float(roc_auc_score(y, scores)), 3),
                     "falseRejectsOnGood": round(float(((dec == "FAIL") & (y == 0)).sum() / max(1, (y == 0).sum())), 3),
                     "escapes": round(float(((dec == "PASS") & (y == 1)).sum() / max(1, (y == 1).sum())), 3),
                     "reviewRate": round(float((dec == "DOUBT").mean()), 3),
                     "calloutsOffBoard": round(off[1] / max(1, off[0]), 3), "callouts": off[0],
                     "passLine": round(float(pol.tau_pass), 4), "failLine": round(float(pol.tau_fail), 4)}
    print(json.dumps(out), flush=True)


if __name__ == "__main__":
    for p in sys.argv[1:] or ["pcb4"]:
        run(p)
