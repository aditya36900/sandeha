"""Build and verify the fixed demo tray: 16 boards per PCB type, one for each situation the station handles.

Every candidate is put through a fresh station (30 references, seed 0, exactly what a built-in line uses). A board is
only chosen if the station handles it the way its caption says, with margin, so the tray behaves the same on every run:

  4 clean boards            -> PASS, no component fault
  up to 6 defect types      -> FAIL (the clearest example of each type)
  1 borderline defect       -> DOUBT: a person decides
  1 unusual but good board  -> DOUBT: a person decides (and clears it)
  1 blurred photo           -> HOLD: too blurred to judge
  1 dark photo              -> HOLD: too dark to judge
  1 different PCB type      -> DOUBT: not this board type
  1 thing that is no board  -> HOLD: not a circuit board

Then the whole tray is run twice more on the same station to check that nothing flips. Writes data/results/demo_tray.json
usage: python scripts/build_demo_tray.py [pcb4 pcb3 pcb2 pcb1]
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SANDEHA_PERSIST", "0")

from sandeha import data, demotray  # noqa: E402
from sandeha.engine import Session  # noqa: E402

OTHER = {"pcb1": "pcb3", "pcb2": "pcb4", "pcb3": "pcb1", "pcb4": "pcb2"}
ORDER = ["missing", "burnt", "wrong place", "extra", "damage", "bent", "melt", "scratch", "dirt"]
SAY = {"missing": "A part is missing", "burnt": "A burnt part", "wrong place": "A part in the wrong place", "extra": "Extra material on the board",
       "damage": "A damaged part", "bent": "A bent pin", "melt": "Melted plastic", "scratch": "A scratched board", "dirt": "Dirt on the board"}
rel = lambda p: str(Path(p).resolve().relative_to(data.VISA_ROOT.resolve())).replace("\\", "/")


def build(prod: str) -> dict:
    s = Session("VisA", prod)
    s.genesis()
    t = time.time()
    while getattr(s, "board", None) is None or not getattr(s, "_board_calibrated", False):
        time.sleep(2)
        if time.time() - t > 900:
            raise RuntimeError("board map did not finish")
    pol = s.cal.policy
    band = pol.tau_fail - pol.tau_pass
    known = {id(x) for x in s.known_defects}
    goods = [x for x in s.eval_pool if x.label == 0]
    bads = [x for x in s.eval_pool if x.label == 1 and id(x) not in known]

    def look(x, kind="board"):
        smp = demotray.DemoSample(path=x.path, kind=kind, label=x.label)
        r = s.inspect(smp.image())
        faults = [f for f in (r.board or {}).get("faults", []) if f.get("level") == "fault"]
        return r, faults

    g_rows = [(x, *look(x)) for x in goods[:70]]
    b_rows = [(x, *look(x)) for x in bads]
    items = []
    add = lambda x, kind, title, expect, truth, defect="good": items.append(
        {"path": rel(x.path), "kind": kind, "title": title, "expect": expect, "truth": truth, "defect": defect})

    clean = sorted([(r.score, x) for x, r, f in g_rows if r.decision == "PASS" and not f and not (r.board or {}).get("faults")
                    and r.score < pol.tau_pass - 0.25 * band], key=lambda t: t[0])
    clean = [x for _, x in clean[:5]]
    by_type = {}
    for x, r, f in b_rows:
        if r.decision == "FAIL" and r.score > pol.tau_fail + 0.3 * band:
            t0 = x.defect_type.split(",")[0].strip()
            if "," not in x.defect_type or t0 not in by_type:
                if t0 not in by_type or r.score > by_type[t0][0]:
                    by_type[t0] = (r.score, x)
    fails = [(t0, by_type[t0][1]) for t0 in ORDER if t0 in by_type][:6]
    mid = pol.tau_pass + 0.5 * band
    doubt_bad = sorted([(abs(r.score - mid), x) for x, r, f in b_rows if r.decision == "DOUBT" and r.doubt_reason == "BORDERLINE"], key=lambda t: t[0])
    doubt_good = sorted([(abs(r.score - mid), x) for x, r, f in g_rows if r.decision == "DOUBT" and r.doubt_reason == "BORDERLINE"], key=lambda t: t[0])

    # the running order tells a story: clean, defects, doubt, then the photos the station must refuse to judge
    seq = []
    if clean:
        seq.append((clean[0], "board", "A clean board", ["PASS"], 0, "good"))
    for i, (t0, x) in enumerate(fails):
        seq.append((x, "board", SAY.get(t0, t0), ["FAIL"], 1, x.defect_type))
        if i == 1 and len(clean) > 1:
            seq.append((clean[1], "board", "A clean board", ["PASS"], 0, "good"))
        if i == 3 and len(clean) > 2:
            seq.append((clean[2], "board", "A clean board", ["PASS"], 0, "good"))
    if doubt_bad:
        seq.append((doubt_bad[0][1], "board", "A faint defect: the station is not sure and asks a person", ["DOUBT"], 1, doubt_bad[0][1].defect_type))
    if doubt_good:
        seq.append((doubt_good[0][1], "board", "A good board that looks unusual: it asks rather than rejects", ["DOUBT"], 0, "good"))
    if len(clean) > 3:
        seq.append((clean[3], "board", "A clean board", ["PASS"], 0, "good"))
    spare = clean[4] if len(clean) > 4 else clean[0]
    seq.append((spare, "blur", "Camera out of focus: it refuses to judge", ["HOLD"], -1, "blurred photo"))
    seq.append((spare, "dark", "The lamp failed: it refuses to judge", ["HOLD"], -1, "dark photo"))
    other = data.load("VisA", OTHER[prod]).train_good[3]
    seq.append((other, "other_board", "A different board type on this line", ["DOUBT", "HOLD"], -1, "wrong board type"))
    thing = data.load("VisA", "cashew").train_good[0]
    seq.append((thing, "not_board", "Not a circuit board at all", ["HOLD"], -1, "not a board"))
    for x, kind, title, expect, truth, defect in seq:
        add(x, kind, title, expect, truth, defect)

    # verify: the whole tray, twice, on the same station
    runs = []
    for _ in range(2):
        row = []
        for it in items:
            smp = demotray.DemoSample(path=data.VISA_ROOT / it["path"], kind=it["kind"], label=it["truth"])
            r = s.inspect(smp.image())
            row.append(r.decision)
        runs.append(row)
    ok = [all(run[i] in it["expect"] for run in runs) for i, it in enumerate(items)]
    for i, it in enumerate(items):
        it["verified"] = bool(ok[i])
        it["seen"] = [run[i] for run in runs]
        print(f"  {i + 1:2d} {'ok ' if ok[i] else 'BAD'} {it['kind']:11s} expect {'/'.join(it['expect']):10s} got {it['seen']} {it['title']} [{it['defect']}]", flush=True)
    kept = [it for it in items if it["verified"]]
    print(prod, f"{len(kept)}/{len(items)} situations verified stable", flush=True)
    return {"items": kept, "built": time.strftime("%Y-%m-%d %H:%M"), "dropped": [it["title"] for it in items if not it["verified"]]}


if __name__ == "__main__":
    out = json.loads(demotray.MANIFEST.read_text()) if demotray.MANIFEST.exists() else {}
    for p in sys.argv[1:] or ["pcb4"]:
        out[p] = build(p)
        demotray.MANIFEST.write_text(json.dumps(out, indent=1))
