"""Are the component flags the right ones? Precision / recall of fault-level component flags vs VisA pixel masks,
through the full engine (board verdict + corroboration gating), compared with 'every non-OK component is a fault'.

usage: python scripts/flag_precision.py pcb4   -> prints one JSON line per product
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SANDEHA_PERSIST", "0")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from sandeha.board import align, to_work  # noqa: E402
from sandeha.engine import Session  # noqa: E402


def main(prod: str, n_bad: int = 60, n_good: int = 30):
    s = Session("VisA", prod)
    s.genesis()
    s.ensure_board(wait=True)
    import time as _t
    while getattr(s, "board", None) is None:  # genesis already started a background build
        _t.sleep(2)
    bm = s.board
    H, W = bm.golden.shape[:2]
    known = {id(x) for x in s.known_defects}
    bad = [x for x in s.product.test if x.label == 1 and id(x) not in known and x.mask_path is not None][:n_bad]
    good = [x for x in s.product.test if x.label == 0][:n_good]
    st = {"gated": [0, 0, 0], "ungated": [0, 0, 0]}  # flags, flags on the true defect, boards with a correct flag
    good_flags = {"gated": 0, "ungated": 0}
    comps = {c.id: c for c in bm.components}
    for x in bad + good:
        img = x.image()
        rec = s.inspect(img, truth=x.label, defect_type=x.defect_type)
        fl = (rec.board or {}).get("faults", [])
        if x.label == 0:
            good_flags["gated"] += sum(f["level"] == "fault" for f in fl)
            good_flags["ungated"] += len(fl)
            continue
        work = to_work(img)
        _, warp = align(work, bm.golden)
        gt = cv2.resize((x.mask() > 0).astype(np.float32), (work.shape[1], work.shape[0]))
        gtw = cv2.warpAffine(gt, warp, (W, H), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP) > 0.5
        gtd = cv2.dilate(gtw.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)

        def hit(f):
            if f["status"] == "EXTRA":
                bx, by, bw, bh = f["bbox"]
                return bool(gtd[int(by * H):int((by + bh) * H) + 1, int(bx * W):int((bx + bw) * W) + 1].any())
            return bool((comps[f["id"]].mask & gtd).any())

        for mode, sel in (("gated", [f for f in fl if f["level"] == "fault"]), ("ungated", fl)):
            hits = [hit(f) for f in sel]
            st[mode][0] += len(sel)
            st[mode][1] += sum(hits)
            st[mode][2] += any(hits)
    out = {"product": prod, "defectiveBoards": len(bad), "goodBoards": len(good)}
    for mode in st:
        f, h, b = st[mode]
        out[mode] = {"flagPrecision": round(h / max(f, 1), 3), "boardRecall": round(b / max(len(bad), 1), 3),
                     "flagsPerDefectiveBoard": round(f / max(len(bad), 1), 2),
                     "faultFlagsPerGoodBoard": round(good_flags[mode] / max(len(good), 1), 2)}
    print(json.dumps(out), flush=True)


if __name__ == "__main__":
    for p in sys.argv[1:] or ["pcb4"]:
        main(p)
