"""Where is the line between 'this board', 'another board' and 'not a board at all'? Measured, per line.

For each saved PCB line: global distance (1 - cosine of the DINOv2 embedding to the nearest reference) of every VisA
test board of that type (good and defective), of 20 boards of each other PCB type, and of non-electronics objects.
The station holds anything above 0.6 as "not a circuit board" and sends anything above max(0.06, 3 x the reference
maximum) to a person as "not this board"; this script shows how much margin those lines have.

usage: python scripts/foreign_check.py        (needs the four PCB lines saved in data/sessions)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import torch  # noqa: E402

from sandeha import data  # noqa: E402
from sandeha.backbone import DEVICE, Backbone  # noqa: E402
from sandeha.shift import global_nonconformity  # noqa: E402

PCBS = ("pcb1", "pcb2", "pcb3", "pcb4")
OBJECTS = ("candle", "cashew", "capsules", "fryum", "macaroni1")


def main() -> None:
    bb = Backbone.get("facebook/dinov2-small", 448)
    lines = {}
    for f in sorted((data.DATA_ROOT / "sessions").glob("*.pt")):
        d = torch.load(f, map_location=DEVICE, weights_only=False)
        if d.get("product") is not None and d["product"].name in PCBS and d["product"].name not in lines:
            lines[d["product"].name] = d
    nov = lambda ims, ref: global_nonconformity(bb(ims).cls.float(), ref).cpu().numpy()
    for name, d in sorted(lines.items()):
        ref = d["gref"].cls.to(DEVICE).float()
        cal = np.asarray(d["global_calib"])
        thr = max(0.06, 3 * float(cal.max()))
        p = data.load("VisA", name)
        own = {0: [], 1: []}
        for i in range(0, len(p.test), 16):
            b = p.test[i:i + 16]
            for s, v in zip(b, nov([s.image() for s in b], ref)):
                own[s.label].append(float(v))
        other = np.concatenate([nov([s.image() for s in data.load("VisA", o).train_good[:20]], ref) for o in PCBS if o != name])
        obj = np.concatenate([nov([s.image() for s in data.load("VisA", o).train_good[:4]], ref) for o in OBJECTS])
        print(f"{name}: this-board line {thr:.3f} | good max {max(own[0]):.3f} | defective max {max(own[1]):.3f} "
              f"({sum(v > thr for v in own[1])}/{len(own[1])} defective boards sent to a person as 'not this board') | "
              f"other PCB types min {other.min():.3f} | non-boards min {obj.min():.3f} (hold line 0.6)", flush=True)


if __name__ == "__main__":
    main()
