"""Approval desk: everything the person physically signing off a board needs, in one dossier.

The system's view (calibrated verdict and its evidence), a critical analysis that argues both sides from the
measurements, what would change the decision, component faults graded against IPC-A-610 with root causes and repair
actions, the closest past boards, the money at risk either way, and (separately, it is slower) what the local
vision-language model sees. The VLM is advisory: it never changes a verdict, and its agreement with the system is shown
so the person can judge it.
"""
from __future__ import annotations

import numpy as np

from . import smt
from .station import STATION


def queue(s) -> list[dict]:
    """Boards waiting for a person: doubts, rejects to confirm, and passes carrying component 'watch' flags."""
    out = []
    for r in s.records:
        if r.ghost or r.review.get("final") in ("GOOD", "DEFECT", "GHOST_CHECKED"):
            continue
        if str(r.synthetic or "").startswith("sentinel"):  # the station's own self-test boards are not production
            continue
        watch = [f for f in (r.board or {}).get("faults", []) if f.get("level") == "watch"]
        if r.decision == "DOUBT":
            why = "I am unsure: a person decides"
        elif r.decision == "FAIL":
            why = "Rejected: confirm before rework or scrap"
        elif watch:
            why = f"Passed, with {len(watch)} component(s) to watch"
        else:
            continue
        risk = r.score / max(s.cal.policy.tau_fail, 1e-9)
        out.append({"part": r.id, "decision": r.decision, "why": why, "image": r.image_url, "score": r.score,
                    "risk": round(float(risk), 3), "votes": len(r.review.get("votes", [])), "synthetic": r.synthetic,
                    "faults": len([f for f in (r.board or {}).get("faults", []) if f.get("level") == "fault"]), "created": r.created})
    out.sort(key=lambda x: ({"DOUBT": 0, "FAIL": 1, "PASS": 2}[x["decision"]], -x["risk"]))
    return out[-200:]


def dossier(s, rid: str) -> dict:
    r = next((x for x in s.records if x.id == rid), None)
    if r is None:
        raise KeyError(rid)
    pol = s.cal.policy
    tp, tf = (r.pass_line or pol.tau_pass), pol.tau_fail
    known = np.asarray(getattr(s, "known_scores", []), np.float32)
    good_above = r.p_value  # share of good references at least this unusual
    defects_below = float((known <= r.score).mean()) if len(known) else None
    comp = smt.enrich(s, r) or {"faults": []}
    faults = [f for f in comp["faults"] if f["level"] == "fault"]
    watch = [f for f in comp["faults"] if f["level"] == "watch"]
    regions = r.regions or []
    prec = r.precedents or []

    case_fail, case_pass = [], []
    if r.score > tf:
        case_fail.append(f"Unusualness {r.score:.3f} is above the fail line {tf:.3f}; only {good_above:.1%} of good reference boards are this unusual.")
    elif r.score > tp:
        case_fail.append(f"Unusualness {r.score:.3f} is above the pass line {tp:.3f} (between the lines: not safe to pass alone).")
    else:
        case_pass.append(f"Unusualness {r.score:.3f} is below the pass line {tp:.3f}: inside what 30 good boards look like.")
    if defects_below is not None:
        (case_fail if defects_below > 0.5 else case_pass).append(
            f"{defects_below:.0%} of the real defective examples were less unusual than this board.")
    for f in faults:
        case_fail.append(f"{f['id']} ({f.get('kind', 'part')}): {f['status'].lower().replace('_', ' ')}. {f['why'][0] if f['why'] else ''} IPC: {f['ipc']['verdict']} ({f['ipc']['rule']}).")
    for g in regions:
        if g.get("realOdds") is not None:
            if g["realOdds"] >= 0.6:
                case_fail.append(f"Region {g['id']} ({g['label']}, {g['severity']}): regions this strong were real defects {g['realOdds']:.0%} of the time.")
            else:
                case_pass.append(f"Region {g['id']} is weak: regions like it were real defects only {g['realOdds']:.0%} of the time (could be a false call).")
    if not faults and r.board:
        case_pass.append(f"All {r.board.get('checked')} components sit where they should and match good boards.")
    if watch:  # one line, not one per part: watch flags are weak evidence by design
        ids = ", ".join(f["id"] for f in watch[:6]) + ("…" if len(watch) > 6 else "")
        case_pass.append(f"{len(watch)} other part(s) ({ids}) have only weak, uncorroborated signals: not enough to call them faulty.")
    if prec:
        p0 = prec[0]
        good_case = "good" in str(p0.get("label", "")).lower()
        (case_pass if good_case else case_fail).append(
            f"The most similar past board was {'a verified good one' if good_case else 'a defective one'} ({p0.get('similarity', 0):.0%} alike).")
    q = r.quality or {}
    if q and (q.get("sharpness", 1) < 0.6 or not 0.6 < q.get("exposure", 1) < 1.5 or q.get("glarePct", 0) > 5):
        case_pass.append(f"Image quality is off (sharpness {q.get('sharpness', 0):.0%}, exposure {q.get('exposure', 0):.0%}): the camera may be the problem, not the board.")
    if r.conditions and any(v not in (0, 0.0, 1, 1.0) for v in r.conditions.values()):
        case_pass.append("Line conditions were changed when this board was scanned (light or camera): unusualness may come from the scene.")

    change = []
    if faults:
        ids = ", ".join(f["id"] for f in faults[:3])
        change.append(f"If you inspect {ids} and they are correct, this is a false call: approve it and say so (it teaches the line after a second person agrees).")
    if r.decision == "DOUBT":
        change.append(f"The board sits {abs(r.score - tp) / max(tf - tp, 1e-9):.0%} of the way into the doubt band; a second view under side light settles most of these.")
    if not faults and r.decision != "PASS":
        change.append("No single component explains the rejection: look at the heatmap's hottest spot before deciding.")
    st = STATION.settings
    p_def = float(min(0.99, max(0.01, 1 - good_above))) if r.decision != "PASS" else float(max(0.0, 1 - (1 - (defects_below or 0))))
    risk = {"passIt": round(p_def * st["costPerEscape"], 1), "rejectIt": round((1 - p_def) * st["costPerFalseReject"], 1),
            "estimatedDefectChance": round(p_def, 3),
            "note": f"expected cost = chance x cost (escape {st['costPerEscape']}, false reject {st['costPerFalseReject']}); "
                    "the chance is a rough guide from where the score sits, not a guarantee"}
    verdict_text = {"PASS": "Passed on its own", "FAIL": "Rejected", "DOUBT": "Needs a person", "HOLD": "Held"}[r.decision]
    return {
        "record": r.to_dict(), "verdict": verdict_text,
        "system": {"score": r.score, "passLine": tp, "failLine": tf, "goodAsUnusual": good_above, "defectsLessUnusual": defects_below,
                   "noveltyP": r.novelty_p, "uncertainty": r.uncertainty, "naive": r.naive_decision, "explanation": r.explanation,
                   "falseRejectGuarantee": pol.alpha_fr},
        "critical": {"caseForFail": case_fail, "caseForPass": case_pass, "whatWouldChangeIt": change,
                     "balance": "fail" if len(case_fail) > len(case_pass) else "pass" if len(case_pass) > len(case_fail) else "even"},
        "components": comp, "regions": regions, "precedents": prec, "counterfactual": r.counterfactual, "risk": risk,
        "review": r.review, "ipcClass": smt._klass(s), "ipcClasses": smt.IPC_CLASSES,
    }


def vlm_view(s, rid: str) -> dict:
    """What the local VLM sees on the flagged spots, and whether it agrees with the system. Advisory only."""
    from . import vlm
    from .visual import load_media

    cache = getattr(s, "_vlm_views", None)
    if cache is None:
        s._vlm_views = cache = {}
    if rid in cache:
        return cache[rid]
    r = next((x for x in s.records if x.id == rid), None)
    if r is None:
        raise KeyError(rid)
    if not vlm.available():
        return {"available": False, "items": []}
    items = []
    whole = load_media(r.image_url)
    for g in (r.regions or [])[:3]:
        crop = load_media(g.get("crop"))
        if crop is None:
            continue
        comp = g.get("component") or {}
        claim = f"{g['label']}" + (f" on {comp.get('kind')} {comp.get('id')}" if comp else "")
        try:
            seen = vlm.generate([crop.resize((336, 336))], "Describe in one sentence what you see in this close-up of a circuit board. "
                                "Mention any visible burn marks, missing parts, solder blobs, bridges or debris. Do not guess causes.", 50)
            agree = vlm.generate([crop.resize((336, 336))], f"An inspection system says this close-up shows: {claim}. Looking only at the image, "
                                 "is there a visible defect here? Answer with one word: yes or no.", 3)
        except Exception as e:  # GPU busy: say so instead of guessing
            items.append({"region": g["id"], "claim": claim, "seen": f"unavailable ({type(e).__name__})", "agrees": None})
            continue
        a = agree.strip().lower()
        items.append({"region": g["id"], "claim": claim, "seen": seen.split("\n")[0], "agrees": a.startswith("yes") if a[:2] in ("ye", "no") else None})
    overall = None
    if whole is not None:
        try:
            overall = vlm.generate([whole.resize((448, 448))], "You are a senior electronics inspector. In two short sentences, say what looks "
                                   "wrong on this assembled circuit board, if anything. Be specific about location. If nothing looks wrong, say so.", 70)
        except Exception:
            overall = None
    n_ok = [i["agrees"] for i in items if i["agrees"] is not None]
    out = {"available": True, "model": vlm.MODEL, "items": items, "overall": overall,
           "agreement": f"{sum(n_ok)}/{len(n_ok)} flagged spots confirmed" if n_ok else "no flagged spots to check",
           "caveat": "Measured on VisA: this 2B model was no better than chance at confirming defects, so it never changes a verdict. Read it as a second pair of eyes, not a judge."}
    cache[rid] = out
    return out
