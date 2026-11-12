"""The electronics manufacturing line around the inspection: process root causes, IPC-A-610 grading, IPC-7912-style
DPMO, first-pass yield, false calls, per-component SPC, rework tickets, feeders and moisture-sensitive parts.

What is measured vs simulated:
  measured  - every number derived from inspected boards (verdicts, component faults, offsets, colours, yields, DPMO).
  simulated - line context this station cannot see from a camera: feeder slots, reel counts, MSD floor-life clocks,
              the reflow profile. Clearly labelled as simulated everywhere it is shown.

References (secondary sources, check the current revisions before relying on them):
  IPC-A-610: side overhang of chip components <= 50% of termination width (Class 1-2), <= 25% (Class 3);
             end overhang never allowed.
  IPC-7912:  component / placement / termination DPMO = defects / opportunities x 1e6; the bare board counts as one
             component opportunity; DPMO index pools all three.
  J-STD-033: floor life at <=30 C / 60% RH: MSL2 1 year, MSL2a 4 weeks, MSL3 168 h, MSL4 72 h, MSL5 48 h, MSL5a 24 h.
"""
from __future__ import annotations

import time
from collections import Counter, defaultdict

import numpy as np

# ------------------------------------------------------------------ the line
STAGES = [
    {"key": "load", "title": "Board loader", "what": "Bare PCBs enter the line, each with a serial (label or laser mark).", "kind": "context"},
    {"key": "print", "title": "Solder paste print", "what": "Stencil printer deposits paste on every pad.", "kind": "context"},
    {"key": "spi", "title": "SPI", "what": "3D solder paste inspection: volume, height, offset of every deposit.", "kind": "context"},
    {"key": "place", "title": "Pick & place", "what": "Nozzles pick parts from feeder reels and place them on the paste.", "kind": "context"},
    {"key": "aoi_pre", "title": "Pre-reflow AOI", "what": "Optional check of placement before soldering.", "kind": "context"},
    {"key": "reflow", "title": "Reflow oven", "what": "Preheat, soak, reflow peak, cool: paste becomes solder joints.", "kind": "context"},
    {"key": "aoi_post", "title": "Post-reflow AOI (Sandeha)", "what": "This station: every component checked, every doubt routed to a person.", "kind": "this"},
    {"key": "test", "title": "ICT / functional test", "what": "Electrical test of the assembled board.", "kind": "context"},
    {"key": "rework", "title": "Rework", "what": "Technicians repair what inspection rejected.", "kind": "context"},
    {"key": "pack", "title": "Pack & ship", "what": "Good boards leave with their traceability record.", "kind": "context"},
]

# where each component fault most likely started, and what to check there
ROOT = {
    "MISSING": ("place", "Pick & place", "nozzle clogged, feeder empty or mis-pick, wrong pickup height", "Check the feeder for this part, the nozzle vacuum and the pick-up log"),
    "SHIFTED": ("place", "Pick & place / paste print", "placement offset or paste printed off the pads (the part floats during reflow)", "Check placement calibration for this location and the SPI offset of its pads"),
    "ROTATED": ("place", "Pick & place / kitting", "reel loaded reversed or wrong rotation in the placement program", "Check the reel orientation and the program rotation for this reference"),
    "WRONG_PART": ("place", "Kitting / feeder setup", "wrong reel on the feeder (BOM / feeder-list mismatch)", "Verify the reel against the feeder list before the next board"),
    "BURNT": ("reflow", "Reflow / electrical stress", "over-temperature in reflow, ESD, or electrical overstress at test", "Check the reflow peak and time-above-liquidus, ESD grounding, and the test fixture"),
    "SOLDER": ("print", "Paste print / reflow", "too much paste (bridge, excess) or too little / poor wetting (dry joint)", "Check stencil aperture and SPI volume for these pads, then the reflow profile"),
    "DAMAGED": ("rework", "Handling", "mechanical damage in handling, depaneling or test", "Check handling between stations and the depaneling stress"),
    "EXTRA": ("print", "Paste print / cleanliness", "solder balls, paste spatter or foreign debris", "Check paste condition, stencil wiping frequency and line cleanliness"),
}

ACTION = {
    "MISSING": "Place the missing {kind} at {id}",
    "SHIFTED": "Re-position {id} onto its pads and reflow the joints",
    "ROTATED": "Remove {id} and re-place it in the correct orientation",
    "WRONG_PART": "Remove {id} and fit the correct part (check the reel)",
    "BURNT": "Replace {id}; investigate the cause before release",
    "SOLDER": "Touch up the solder joints of {id} (remove bridge / add solder)",
    "DAMAGED": "Inspect {id}; replace if cracked or chipped",
    "EXTRA": "Remove debris / solder balls at {id} and clean the area",
}

TERMINATIONS = {"resistor": 2, "capacitor": 2, "inductor": 2, "diode / LED": 2, "transistor": 3, "IC": 8,
                "connector": 5, "hole / pad": 1, "metal part": 2, "other": 2}

IPC_CLASSES = {1: "Class 1 - general electronics", 2: "Class 2 - dedicated service (industrial, consumer)",
               3: "Class 3 - high reliability (medical, aerospace, automotive safety)"}

MSL_HOURS = {"2": 8760, "2a": 672, "3": 168, "4": 72, "5": 48, "5a": 24}


def ipc_grade(fault: dict, comp_bbox_px: tuple[int, int, int, int] | None, klass: int) -> dict:
    """IPC-A-610-inspired grading of one component fault (inspired, not certified)."""
    st = fault["status"]
    if st == "SHIFTED" and comp_bbox_px is not None:
        m = fault.get("measured") or {}
        w, h = comp_bbox_px[2], comp_bbox_px[3]
        dx, dy = abs(float(m.get("dx", 0))), abs(float(m.get("dy", 0)))
        # side overhang: displacement across the part's short axis, as a share of that width
        across = dy if w >= h else dx
        along = dx if w >= h else dy
        width = max(1.0, min(w, h))
        pct = 100.0 * across / width
        limit = 25.0 if klass == 3 else 50.0
        if along > 0.25 * max(w, h):
            return {"verdict": "defect", "rule": f"end overhang ({along:.0f} px along the part) is not allowed in any class", "overhangPct": round(pct, 1)}
        if pct > limit:
            return {"verdict": "defect", "rule": f"side overhang {pct:.0f}% of width > {limit:.0f}% allowed for Class {klass}", "overhangPct": round(pct, 1)}
        return {"verdict": "process indicator", "rule": f"side overhang {pct:.0f}% of width is within the {limit:.0f}% Class {klass} limit: acceptable, but watch the process", "overhangPct": round(pct, 1)}
    if st == "DAMAGED":
        return {"verdict": "defect" if klass == 3 else "defect if functional damage",
                "rule": "body damage exposing the element is a defect; cosmetic marks may be acceptable in Class 1-2"}
    if st == "EXTRA":
        return {"verdict": "defect", "rule": "solder balls / debris that can bridge conductors are defects in all classes"}
    return {"verdict": "defect", "rule": {"MISSING": "missing component", "ROTATED": "wrong orientation / polarity",
                                          "WRONG_PART": "wrong component", "BURNT": "heat or electrical damage",
                                          "SOLDER": "solder bridge or insufficient wetting"}.get(st, st.lower()) + ": defect in all classes"}


# ------------------------------------------------------------------ helpers over a session
def _boards(s, synthetic: bool = False):
    return [r for r in s.records if r.board is not None and not r.ghost and (bool(r.synthetic) == synthetic)]


def _comp_map(s):
    bm = getattr(s, "board", None)
    return {c.id: c for c in bm.components} if bm else {}


def _klass(s) -> int:
    return int(getattr(s, "ipc_class", 2))


def enrich(s, rec) -> dict | None:
    """One board's component faults with IPC grade, root cause and repair action."""
    if rec.board is None:
        return None
    comps = _comp_map(s)
    k = _klass(s)
    out = []
    for f in rec.board.get("faults", []):
        c = comps.get(f["id"])
        g = ipc_grade(f, c.bbox if c else None, k)
        stage, where, cause, check = ROOT.get(f["status"], ("aoi_post", "-", "-", "-"))
        out.append({**{x: f[x] for x in ("id", "status", "level", "kind") if x in f}, "why": f.get("why", []),
                    "ipc": g, "stage": stage, "origin": where, "cause": cause, "check": check,
                    "action": ACTION.get(f["status"], "Inspect {id}").format(id=f["id"], kind=(c.kind if c else "part"))})
    return {"faults": out, "checked": rec.board.get("checked"), "ok": rec.board.get("ok")}


def metrics(s) -> dict:
    """First-pass yield, false calls, escapes, IPC-7912-style DPMO and Paretos, on real (non-synthetic) boards."""
    comps = _comp_map(s)
    boards = _boards(s)
    n = len(boards)
    k = _klass(s)
    passed_first = sum(r.decision == "PASS" for r in boards)
    flagged = [r for r in boards if r.decision in ("FAIL", "DOUBT")]
    known_good = lambda r: r.truth == 0 or r.review.get("final") == "GOOD"  # noqa: E731
    false_calls = sum(known_good(r) for r in flagged)
    escapes = sum(r.decision == "PASS" and (r.truth == 1 or r.review.get("final") == "DEFECT") for r in boards)
    n_comp = len(comps)
    terms = sum(TERMINATIONS.get(c.kind, 2) for c in comps.values())
    dc = dp = dt = 0
    by_ref, by_kind, by_stage, by_status, by_ipc = Counter(), Counter(), Counter(), Counter(), Counter()
    for r in boards:
        if r.decision == "PASS":
            continue
        for f in r.board.get("faults", []):
            if f.get("level") != "fault":
                continue
            st = f["status"]
            c = comps.get(f["id"])
            by_ref[f["id"]] += 1
            by_kind[c.kind if c else "extra material"] += 1
            by_status[st] += 1
            by_stage[ROOT.get(st, ("aoi_post",))[0]] += 1
            by_ipc[ipc_grade(f, c.bbox if c else None, k)["verdict"]] += 1
            if st in ("MISSING", "WRONG_PART", "BURNT", "DAMAGED"):
                dc += 1
            elif st in ("SHIFTED", "ROTATED"):
                dp += 1
            elif st == "SOLDER":
                dt += 1
            else:  # EXTRA: a defect on the board itself (the PCB is one component opportunity)
                dc += 1
    oc, op, ot = n * (n_comp + 1), n * n_comp, n * terms
    dpmo = lambda d, o: round(1e6 * d / o, 1) if o else None  # noqa: E731
    return {
        "boards": n, "components": n_comp, "terminationsPerBoard": terms,
        "firstPassYield": round(passed_first / n, 4) if n else None,
        "flagged": len(flagged), "falseCalls": false_calls,
        "falseCallRate": round(false_calls / len(flagged), 4) if flagged else None,
        "escapes": escapes,
        "dpmo": {"component": dpmo(dc, oc), "placement": dpmo(dp, op), "termination": dpmo(dt, ot),
                 "index": dpmo(dc + dp + dt, oc + op + ot), "defects": {"component": dc, "placement": dp, "termination": dt},
                 "opportunities": {"component": oc, "placement": op, "termination": ot},
                 "note": "IPC-7912 style; terminations per part estimated from its type"},
        "pareto": {"reference": by_ref.most_common(12), "kind": by_kind.most_common(), "status": by_status.most_common(),
                   "stage": [(x["key"], x["title"], by_stage.get(x["key"], 0)) for x in STAGES if by_stage.get(x["key"])],
                   "ipc": by_ipc.most_common()},
        "ipcClass": k, "ipcClasses": IPC_CLASSES,
        "synthetic": len(_boards(s, synthetic=True)),
    }


def spc(s, comp_id: str) -> dict:
    """Control chart of one component's placement offset and colour across inspected boards."""
    c = _comp_map(s).get(comp_id)
    if c is None:
        raise KeyError(comp_id)
    pts = []
    for r in _boards(s):
        m = (r.board.get("m") or {}).get(comp_id)
        if m is None:
            continue
        pts.append({"part": r.id, "offset": m[0], "dL": m[1], "decision": r.decision, "t": r.created})
    st = c.stats
    off = np.array([p["offset"] for p in pts], np.float32)
    rules = []
    if len(off) >= 8:
        centre = float(np.median(off))
        tail = off[-8:]
        if (tail > centre).all():
            rules.append("8 boards in a row above the centre line: placement is drifting")
        if len(off) >= 7 and (np.diff(off[-7:]) > 0).all():
            rules.append("7 boards in a row increasing: a trend, check the placement head for this location")
        if (off[-3:] > 0.66 * st["offsetMax"]).sum() >= 2:
            rules.append("2 of the last 3 boards in the outer third of the limit")
    return {"component": comp_id, "kind": c.kind, "points": pts[-200:],
            "limits": {"offsetUCL": round(st["offsetMax"], 2), "dLLCL": round(st["dLMin"], 2),
                       "offsetCentre": round(float(np.median(off)), 2) if len(off) else None},
            "rules": rules, "calibration": getattr(s.board, "calibration", None)}


def rework_list(s) -> list[dict]:
    tickets = getattr(s, "rework", None)
    if tickets is None:
        s.rework = tickets = {}
    out = []
    for r in s.records:
        if r.board is None or r.ghost or not (r.decision == "FAIL" or r.review.get("final") == "DEFECT"):
            continue
        e = enrich(s, r)
        faults = [f for f in e["faults"] if f["level"] == "fault"]
        if not faults:
            continue
        t = tickets.get(r.id, {"status": "OPEN"})
        out.append({"part": r.id, "image": r.image_url, "heat": r.heat_url, "created": r.created, "synthetic": r.synthetic,
                    "actions": [{"id": f["id"], "status": f["status"], "action": f["action"], "ipc": f["ipc"]["verdict"]} for f in faults],
                    **t})
    out.sort(key=lambda x: (x["status"] != "OPEN", x["created"]), reverse=False)
    return out


def close_ticket(s, rid: str, outcome: str, who: str) -> dict:
    if outcome not in ("REPAIRED", "SCRAPPED", "NO_FAULT_FOUND"):
        raise ValueError("outcome must be REPAIRED, SCRAPPED or NO_FAULT_FOUND")
    if not hasattr(s, "rework"):
        s.rework = {}
    s.rework[rid] = {"status": outcome, "by": who, "closed": time.strftime("%Y-%m-%d %H:%M:%S")}
    rec = next((r for r in s.records if r.id == rid), None)
    if rec is not None and outcome == "NO_FAULT_FOUND" and not rec.review.get("final"):
        rec.review["reworkNoFault"] = who  # a technician's 'no fault found' is evidence of a false call
    return s.rework[rid]


# ------------------------------------------------------------------ simulated line context (clearly labelled)
def materials(s) -> dict:
    """Feeders, reels and moisture-sensitive parts. SIMULATED: this station has no feeder data; the assignment is
    derived from the component map so it stays consistent with the board."""
    comps = list(_comp_map(s).values())
    groups = defaultdict(list)
    for c in comps:
        if c.kind in ("hole / pad", "metal part"):
            continue
        size = "large" if c.area > 1500 else "small"
        groups[(c.kind, size)].append(c.id)
    boards = len([r for r in s.records if not r.ghost])
    rng = np.random.default_rng(abs(hash(s.id)) % (2 ** 32))
    feeders = []
    t0 = getattr(s, "_materials_t0", None) or time.time()
    s._materials_t0 = t0
    for i, ((kind, size), refs) in enumerate(sorted(groups.items())):
        reel = int(rng.choice([1000, 2000, 3000, 5000])) if kind in ("resistor", "capacitor") else int(rng.choice([250, 500, 1000]))
        used = boards * len(refs)
        left = max(0, reel - used - int(rng.integers(0, reel // 3)))
        msl = None
        if kind in ("IC", "transistor", "diode / LED"):
            msl = str(rng.choice(["2a", "3", "3", "4"]))
        opened_h = float((time.time() - t0) / 3600 + rng.uniform(5, 150))
        floor = MSL_HOURS.get(msl) if msl else None
        feeders.append({
            "slot": f"F{i + 1:02d}", "kind": kind, "package": f"{size} {kind}", "references": refs, "perBoard": len(refs),
            "reelSize": reel, "left": left, "boardsLeft": left // max(1, len(refs)),
            "msl": msl, "openedHoursAgo": round(opened_h, 1) if msl else None,
            "floorLifeHours": floor, "floorLeftHours": round(floor - opened_h, 1) if floor else None,
            "status": ("BAKE BEFORE USE" if floor and opened_h > floor else "LOW" if left // max(1, len(refs)) < 50 else "OK"),
        })
    return {"simulated": True, "feeders": feeders,
            "note": "Simulated line context: feeder slots, reel counts and MSD clocks are generated from this board's component map. "
                    "Floor-life limits follow J-STD-033 at <=30 C / 60% RH."}


def reflow_profile(s) -> dict:
    """A typical lead-free (SAC305) reflow profile with zone checks. SIMULATED oven data."""
    rng = np.random.default_rng(abs(hash(s.id + str(len(s.records) // 25))) % (2 ** 32))
    peak = float(rng.normal(245, 3))
    tal = float(rng.normal(70, 8))
    t = np.arange(0, 330, 5)
    temp = np.interp(t, [0, 90, 180, 210, 210 + tal / 2, 240 + tal / 2, 330], [25, 150, 185, 217, peak, 217, 60])
    temp = temp + rng.normal(0, 0.8, len(t))
    checks = [
        {"name": "Preheat ramp", "value": f"{(150 - 25) / 90:.1f} C/s", "spec": "1-3 C/s", "ok": True},
        {"name": "Soak 150-185 C", "value": "90 s", "spec": "60-120 s", "ok": True},
        {"name": "Time above liquidus (217 C)", "value": f"{tal:.0f} s", "spec": "60-90 s", "ok": 60 <= tal <= 90},
        {"name": "Peak", "value": f"{peak:.0f} C", "spec": "235-250 C", "ok": 235 <= peak <= 250},
    ]
    return {"simulated": True, "points": [{"t": int(a), "temp": round(float(b), 1)} for a, b in zip(t, temp)],
            "checks": checks, "liquidus": 217,
            "note": "Simulated oven data for a SAC305 lead-free profile; connect the oven's profiler to make it real."}


def line_overview(s) -> dict:
    m = metrics(s)
    by_stage = {k: v for k, _, v in m["pareto"]["stage"]}
    stages = [{**st, "faults": by_stage.get(st["key"], 0)} for st in STAGES]
    recent = []
    for r in reversed(s.records[-60:]):
        if r.board is None or r.ghost:
            continue
        e = enrich(s, r)
        if e and any(f["level"] == "fault" for f in e["faults"]):
            recent.append({"part": r.id, "decision": r.decision, "image": r.image_url, "synthetic": r.synthetic,
                           "faults": [f for f in e["faults"] if f["level"] == "fault"][:5]})
        if len(recent) >= 8:
            break
    return {"stages": stages, "metrics": m, "recent": recent, "root": {k: {"stage": v[0], "origin": v[1], "cause": v[2], "check": v[3]} for k, v in ROOT.items()},
            "reflow": reflow_profile(s)}



def xray(s) -> dict:
    """Board X-ray: physical layers, copper connectivity, and where faults have concentrated across real boards."""
    import base64
    import io

    import cv2
    from PIL import Image

    bm = getattr(s, "board", None)
    if bm is None:
        return {"status": "none"}
    lay = dict(bm.layers())
    H, W = bm.golden.shape[:2]
    dens = np.zeros((H, W), np.float32)
    comps = {c.id: c for c in bm.components}
    n, counts = 0, Counter()
    for r in _boards(s):
        n += 1
        for f in r.board.get("faults", []):
            if f.get("level") != "fault":
                continue
            if f["status"] == "EXTRA" and f.get("bbox"):
                x, y, w, h = f["bbox"]
                dens[int(y * H):int((y + h) * H) + 1, int(x * W):int((x + w) * W) + 1] += 1
            elif f["id"] in comps:
                dens[comps[f["id"]].mask] += 1
                counts[f["id"]] += 1
    img = np.zeros((H, W, 4), np.uint8)
    if dens.max() > 0:
        d = cv2.GaussianBlur(dens, (0, 0), 6)
        d = d / d.max()
        img[..., 0] = 255
        img[..., 1] = (190 * (1 - d)).astype(np.uint8)
        img[..., 2] = 60
        img[..., 3] = (np.clip(d * 1.4, 0, 1) * 230).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(img, "RGBA").save(buf, format="PNG", optimize=True)
    layers = list(lay["layers"]) + [{"key": "failures", "title": "Failure density", "image": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(),
                                     "what": f"where faults concentrated over {n} real boards (measured)"}]
    pub = s.board_public()
    return {"status": "ready", "size": lay["size"], "layers": layers, "nets": lay["nets"], "edges": lay["edges"], "coverage": lay["coverage"],
            "components": pub.get("components", []), "golden": pub.get("golden"), "boards": n, "failCounts": dict(counts),
            "note": lay["note"]}


def pulse(s, n: int = 80) -> dict:
    """Line pulse: components x boards matrix of drift (measured), plus the atlas of every defect close-up found."""
    bm = getattr(s, "board", None)
    boards = [r for r in _boards(s)][-n:]
    comps = bm.components if bm else []
    rows = []
    for c in comps:
        st = c.stats
        cells = []
        for r in boards:
            m = (r.board.get("m") or {}).get(c.id)
            f = next((x for x in r.board.get("faults", []) if x["id"] == c.id), None)
            if m is None:
                cells.append(None)
                continue
            off = abs(m[0]) / max(st["offsetMax"], 1e-6)
            dl = abs(m[1]) / max(abs(st["dLMin"]), 1e-6)
            cells.append({"v": round(min(2.0, max(off, dl)), 3), "offset": m[0], "dL": m[1],
                          "status": f["status"] if f else "OK", "level": f["level"] if f else None})
        vals = [x["v"] for x in cells if x]
        rows.append({"id": c.id, "kind": c.kind, "cells": cells, "mean": round(float(np.mean(vals)), 3) if vals else 0.0,
                     "faults": sum(1 for x in cells if x and x["level"] == "fault")})
    rows.sort(key=lambda r: (-r["faults"], -r["mean"]))
    atlas: dict = {}
    for r in reversed(s.records):
        if r.ghost:
            continue
        for g in r.regions or []:
            if not g.get("crop"):
                continue
            atlas.setdefault(g["label"], []).append({"crop": g["crop"], "part": r.id, "severity": g["severity"], "decision": r.decision,
                                                     "component": (g.get("component") or {}).get("id"), "synthetic": bool(r.synthetic)})
    atlas_out = [{"label": k, "count": len(v), "items": v[:24]} for k, v in sorted(atlas.items(), key=lambda kv: -len(kv[1]))]
    return {"boards": [{"id": r.id, "decision": r.decision, "created": r.created, "synthetic": bool(r.synthetic)} for r in boards],
            "components": rows, "atlas": atlas_out, "stream": [{"id": r.id, "decision": r.decision} for r in s.records[-60:] if not r.ghost]}
