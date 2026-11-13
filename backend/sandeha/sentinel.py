"""Sentinel: the station audits itself, live.

Every few real boards it plants one known fault on a held-out good board (a board it never learned from and never
inspected), inspects it exactly like a production board, and keeps score. The result is a catch rate per fault type
measured on THIS line as it is NOW - not a lab number from a brochure. If the lighting changes or a lens fogs, the
planted faults start slipping through before real defects do, and the station raises an alarm with the receipts.
Audited boards are marked synthetic: they never count in yield, DPMO or the approval queue.
"""
from __future__ import annotations

import time
from collections import defaultdict

import numpy as np

from .board import FAULTS, plant_fault
from .station import STATION

KINDS = ("missing", "shifted", "rotated", "burnt", "solder_bridge", "solder_dry")
TITLE = {"missing": "Missing part", "shifted": "Shifted part", "rotated": "Rotated / reversed", "burnt": "Burnt part",
         "solder_bridge": "Solder bridge / excess", "solder_dry": "Dry joint"}
WINDOW = 24  # recent audits per kind for the live rate


def audit(s) -> dict | None:
    bm = getattr(s, "board", None)
    if bm is None:
        return None
    pool = [x for x in s.eval_pool if x.label == 0] or s.spare_good
    if not pool:
        return None
    rng = np.random.default_rng()
    counts = {k: 0 for k in KINDS}
    for a in getattr(s, "audits", []):
        counts[a["kind"]] = counts.get(a["kind"], 0) + 1
    kind = min(KINDS, key=lambda k: (counts.get(k, 0), rng.random()))  # keep the kinds balanced
    # audit real parts an inspector cares about, not pad-sized specks the segmentation also found
    real = ("IC", "connector", "capacitor", "resistor", "diode / LED", "inductor", "transistor")
    cands = [c for c in bm.components if c.kind in real and c.area >= 800] or [c for c in bm.components if c.area >= 800] or list(bm.components)
    if kind == "rotated":
        cands = [c for c in cands if c.kind in ("IC", "diode / LED", "transistor", "other")] or cands
    w = np.sqrt(np.array([c.area for c in cands], np.float64))  # bigger parts are audited more often, like a human would
    comp = cands[int(rng.choice(len(cands), p=w / w.sum()))]
    base = pool[int(rng.integers(len(pool)))].image()
    img = plant_fault(base, bm, comp.id, kind, rng)
    t = time.time()
    rec = s.inspect(img, truth=1, defect_type=f"sentinel {kind.replace('_', ' ')} on {comp.id}")
    rec.synthetic = f"sentinel: {kind} on {comp.id}"
    rec.truth = None  # never in the real metrics
    flagged = next((f for f in (rec.board or {}).get("faults", []) if f["id"] == comp.id), None)
    a = {"t": rec.created, "part": rec.id, "kind": kind, "component": comp.id, "compKind": comp.kind,
         "decision": rec.decision, "stopped": rec.decision != "PASS",
         "located": bool(flagged and flagged.get("level") == "fault"), "status": flagged["status"] if flagged else None,
         "ms": round(1000 * (time.time() - t))}
    if not hasattr(s, "audits"):
        s.audits = []
    s.audits.append(a)
    del s.audits[:-400]
    s.emit("sentinel.audit", message=f"Sentinel planted a {TITLE[kind].lower()} on {comp.id}: {'stopped' if a['stopped'] else 'MISSED'}"
           + (", located" if a["located"] else ""), audit=a)
    _check_alarm(s)
    return a


def _rates(audits: list[dict]) -> dict:
    by = defaultdict(list)
    for a in audits:
        by[a["kind"]].append(a)
    out = {}
    for k in KINDS:
        rows = by.get(k, [])
        recent = rows[-WINDOW:]
        out[k] = {"title": TITLE[k], "n": len(rows), "recentN": len(recent),
                  "stopped": round(sum(a["stopped"] for a in recent) / len(recent), 3) if recent else None,
                  "located": round(sum(a["located"] for a in recent) / len(recent), 3) if recent else None,
                  "allTimeStopped": round(sum(a["stopped"] for a in rows) / len(rows), 3) if rows else None,
                  "trail": [1 if a["stopped"] else 0 for a in recent]}
    return out


def _check_alarm(s) -> None:
    """Baseline = the first WINDOW audits of a kind; alarm when the recent rate falls well below it."""
    audits = getattr(s, "audits", [])
    by = defaultdict(list)
    for a in audits:
        by[a["kind"]].append(a)
    for k, rows in by.items():
        if len(rows) < 2 * 8:
            continue
        base = np.mean([a["stopped"] for a in rows[:8]])
        recent = np.mean([a["stopped"] for a in rows[-8:]])
        if base >= 0.6 and recent <= base - 0.4:
            STATION.raise_alert(f"Sensitivity dropped: {TITLE[k].lower()} ({s.product.name})",
                                f"Planted {TITLE[k].lower()}s were stopped {base:.0%} of the time at first, {recent:.0%} in the last 8. "
                                "Check lighting, focus and the camera before trusting passes.", "WARNING", "SHIFT", s.id)


def report(s) -> dict:
    audits = list(getattr(s, "audits", []))
    rates = _rates(audits)
    n_real = sum(1 for r in s.records if not r.synthetic and not r.ghost)
    known = [a for a in audits]
    overall = round(sum(a["stopped"] for a in known) / len(known), 3) if known else None
    located = round(sum(a["located"] for a in known) / len(known), 3) if known else None
    weakest = min((k for k in KINDS if rates[k]["recentN"] >= 3), key=lambda k: rates[k]["stopped"], default=None)
    return {"audits": len(audits), "realBoards": n_real, "everyNBoards": 5, "window": WINDOW,
            "overallStopped": overall, "overallLocated": located, "kinds": rates,
            "recent": list(reversed(audits[-30:])), "weakest": weakest,
            "boardReady": getattr(s, "board", None) is not None,
            "note": "Planted on held-out good boards the station never learned from. 'Stopped' = the board did not pass; "
                    "'located' = the right component was named. Dry joints are known to be invisible from one top-down camera; "
                    "the number here is the proof, not a hope."}
