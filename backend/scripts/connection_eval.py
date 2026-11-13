"""How good is the wiring map and the connection check? Measured per board type.

  * the map: pads, conductors (nets), point-to-point links found on the golden board
  * false alarms: held-out GOOD VisA test boards with any connection fault reported (should be near zero)
  * planted faults on held-out good boards: a solder bridge between two conductors, a joint with its solder gone,
    a wire cut across. "caught" = a fault of that kind is reported; "located" = on the right pads / conductor
  * real VisA defective boards with a connection finding, by defect type (context only: VisA has no labelled
    opens or shorts, so the planted faults are the ground truth here)

usage: python scripts/connection_eval.py [pcb1 pcb2 pcb3 pcb4]     writes data/results/connections.json
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from sandeha import data  # noqa: E402
from sandeha.board import BoardMap  # noqa: E402
from sandeha.connect import ConnMap, hi_align, plant  # noqa: E402

OUT = data.DATA_ROOT / "results"


def run(name: str, n_good: int = 60, n_plant: int = 40) -> dict:
    prod = data.load("VisA", name)
    refs, known, ev = prod.few_shot(30, 5, 0)
    used = {id(s) for s in refs}
    spare = [s for s in prod.train_good if id(s) not in used][:40]
    ref_imgs = [s.image() for s in refs]
    bm = BoardMap.build(ref_imgs, None, None)
    cm = ConnMap.build(bm, ref_imgs + [s.image() for s in spare])
    pub = cm.public()
    (OUT / "wiring").mkdir(parents=True, exist_ok=True)
    cm.wiring_image().save(OUT / "wiring" / f"{name}.jpg", quality=88)
    print(name, "pads", pub["pads"], "conductors", len(pub["nets"]), "links", pub["links"], "copper visible", pub["twoTone"], flush=True)

    goods = [s for s in ev if s.label == 0][:n_good]
    fa = Counter()
    for s in goods:
        r = cm.check(hi_align(s.image(), bm))
        fa["any"] += not r["ok"]
        fa["open"] += bool([o for o in r["opens"] if not o["sameAs"]])
        fa["short"] += bool(r["shorts"])
        fa["wire"] += bool(r["traces"])
    rng = np.random.default_rng(0)
    planted = {}
    for kind in ("short", "open", "cut"):
        caught = located = n = 0
        for s in goods[:n_plant]:
            out = plant(s.image(), bm, cm, kind, rng)
            if out is None:
                continue
            a, truth = out
            r = cm.check(a)
            n += 1
            if kind == "short":
                caught += bool(r["shorts"])
                located += any({x["a"], x["b"]} == {truth["a"], truth["b"]} for x in r["shorts"])
            elif kind == "open":
                caught += bool(r["opens"])
                located += any(o["pad"] == truth["pad"] for o in r["opens"])
            else:
                caught += bool(r["traces"])
                located += any(t["net"] == truth["net"] and t.get("cut") for t in r["traces"])
        planted[kind] = {"n": n, "caught": round(caught / max(n, 1), 3), "located": round(located / max(n, 1), 3)}
    by = defaultdict(lambda: [0, 0])
    for s in [x for x in ev if x.label == 1]:
        r = cm.check(hi_align(s.image(), bm))
        for t in {x.strip() for x in s.defect_type.split(",")}:
            by[t][0] += not r["ok"]
            by[t][1] += 1
    res = {"product": name, "pads": pub["pads"], "conductors": len(pub["nets"]), "links": pub["links"], "copperVisible": pub["twoTone"],
           "goodBoards": len(goods), "falseAlarms": {k: round(fa[k] / max(1, len(goods)), 3) for k in ("any", "open", "short", "wire")},
           "planted": planted, "realDefects": {t: {"flagged": a, "of": b} for t, (a, b) in sorted(by.items())}}
    print(json.dumps(res), flush=True)
    return res


def cm_net(cm, pad_id):
    return next((p["net"] for p in cm.pads if p["id"] == pad_id), None)


if __name__ == "__main__":
    f = OUT / "connections.json"
    out = json.loads(f.read_text()) if f.exists() else {}
    for nm in sys.argv[1:] or ["pcb1", "pcb2", "pcb3", "pcb4"]:
        out[nm] = run(nm)
        f.write_text(json.dumps(out, indent=1))
