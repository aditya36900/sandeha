"""Ask Sandeha: a grounded, multilingual copilot over the inspection evidence - fully local.

Answers come only from the session's own evidence (scores, thresholds, named defect regions, precedents, reviews,
guard state) plus the part photo itself. The model is Qwen2-VL-2B-Instruct (Apache-2.0) running on the station
GPU: no cloud, no API key, nothing leaves the plant. If the model is not downloaded or the GPU is busy, a
deterministic template engine answers the common questions from the same evidence.
"""
from __future__ import annotations

import re

from PIL import Image

from . import vlm

LANGS = vlm.LANG


def _evidence(session, record_id: str | None) -> dict:
    pol = session.cal.policy.to_dict()
    ev = {
        "product": f"{session.source}/{session.name}", "plant": session.plant,
        "references": len(session.ref_images), "policy": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in pol.items()},
        "shiftAlarm": bool(session.guard.alarmed), "conditions": session.conditions.__dict__,
        "performanceSoFar": session.performance(), "forecast": {k: v for k, v in session.forecast.items() if k != "ewma"},
        "learnedDefects": [d["label"] for d in session.learned_defects],
        "hiveLibrary": [f["label"] for f in session.hive_library],
    }
    rec = None
    if record_id:
        rec = next((r for r in session.records if r.id == record_id), None)
    elif session.records:
        rec = session.records[-1]
    if rec:
        ev["record"] = {"id": rec.id, "decision": rec.decision, "doubtReason": rec.doubt_reason, "score": rec.score,
                        "uncertainty": rec.uncertainty, "pValueVsGoodParts": rec.p_value, "noveltyP": rec.novelty_p,
                        "hotspot": rec.hotspot, "explanation": rec.explanation, "naiveSystemWouldSay": rec.naive_decision,
                        "review": rec.review, "hiveMatch": rec.hive_match,
                        "defectRegions": [{k: g.get(k) for k in ("id", "label", "severity", "areaPct", "centroid", "realOdds", "namedBy")}
                                          for g in (getattr(rec, "regions", None) or [])]}
        ev["precedents"] = [{k: v for k, v in p.items() if k in ("kind", "label", "similarity", "record")}
                            for p in rec.precedents]
    return ev


def _offline(q: str, ev: dict, lang: str) -> str:
    ql = q.lower()
    r = ev.get("record")
    pol = ev["policy"]
    regs = (r or {}).get("defectRegions") or []
    if r and regs and any(w in ql for w in ("what", "wrong", "where", "defect", "kya", "emiti")):
        parts = [f"{g['id']}: {g['label']} ({g['severity']}, {g['areaPct']}% of the part)" for g in regs]
        txt = f"I marked {len(regs)} region(s) on part {r['id']}: " + "; ".join(parts) + " [record.defectRegions]."
    elif r and any(w in ql for w in ("why", "reject", "fail", "doubt", "pass", "kyun", "enduku")):
        txt = f"{r['explanation']} [record.explanation]"
        if ev.get("precedents"):
            p = ev["precedents"][0]
            txt += f" The closest verified good part has similarity {p['similarity']} [precedent 1]."
        if r["naiveSystemWouldSay"] != r["decision"]:
            txt += f" A single-threshold system would have said {r['naiveSystemWouldSay']} [record.naiveSystemWouldSay]."
    elif any(w in ql for w in ("guarantee", "promise", "escape", "ppm", "trust")):
        txt = (f"Good parts are wrongly rejected at most {pol['alpha_fr']:.0%} of the time [policy.alpha_fr]. "
               f"Estimated defect escape is {pol['promised_escape']:.1%}, upper bound {pol['escape_upper_90']:.1%} at 90% "
               f"confidence [policy.escape_upper_90], from {pol['n_good_calib']} good and {pol['n_defect_calib']} defect "
               f"calibration samples.")
    elif any(w in ql for w in ("shift", "light", "condition", "changed")):
        txt = ("The shift alarm is ON: auto-pass is suspended until 5 confirmed good parts are shown [shiftAlarm]."
               if ev["shiftAlarm"] else "No shift detected: the line still looks like the references [shiftAlarm].")
    elif any(w in ql for w in ("forecast", "wear", "storm", "future")):
        f = ev["forecast"]
        txt = (f"Forecast status {f.get('status')} [forecast.status]"
               + (f"; about {f['partsUntilStorm']} parts until weak defects cross the pass line [forecast.partsUntilStorm]."
                  if f.get("partsUntilStorm") else "."))
    else:
        txt = "I can only answer from the inspection evidence: decisions, guarantees, shift status, forecasts and reviews."
    if lang != "en":
        txt += f" (Template mode: reply shown in English; {LANGS.get(lang, lang)} needs the local vision-language model.)"
    return txt


def _where(c) -> str:
    x, y = c
    v = "top" if y < 0.36 else "bottom" if y > 0.64 else "middle"
    h = "left" if x < 0.36 else "right" if x > 0.64 else "centre"
    return "centre" if (v, h) == ("middle", "centre") else f"{v}-{h}" if v != "middle" else f"middle-{h}"


def facts(ev: dict) -> str:
    """The evidence as short numbered facts a small local model can follow (positions computed here, not guessed)."""
    pol = ev["policy"]
    out = [f"[product] {ev['product']} at {ev['plant']}, learned from {ev['references']} good photos."]
    r = ev.get("record")
    if r:
        out.append(f"[record.decision] Part {r['id']} was judged {r['decision']}"
                   + (f" ({r['doubtReason']})" if r.get("doubtReason") else "") + ".")
        out.append(f"[record.score] Unusualness {r['score']:.3f}; pass line {pol['tau_pass']:.3f}, fail line {pol['tau_fail']:.3f}.")
        for g in r.get("defectRegions") or []:
            odds = f", regions like this were real defects {round(100 * g['realOdds'])}% of the time" if g.get("realOdds") is not None else ""
            out.append(f"[region {g['id']}] looks most like '{g['label']}' (a guess from labelled examples), {g['severity']}, "
                       f"{g['areaPct']}% of the part, at the {_where(g['centroid'])} of the photo{odds}.")
        if not r.get("defectRegions") and r["decision"] in ("FAIL", "DOUBT"):
            out.append("[record.defectRegions] No single spot stands out; the part is unusual overall.")
        out.append(f"[record.explanation] {r['explanation']}")
        if r.get("naiveSystemWouldSay") and r["naiveSystemWouldSay"] != r["decision"]:
            out.append(f"[record.naiveSystemWouldSay] A single-threshold system would have said {r['naiveSystemWouldSay']}.")
    out.append(f"[policy.alpha_fr] Good parts are wrongly rejected at most {pol['alpha_fr']:.0%} of the time.")
    out.append(f"[shiftAlarm] Conditions-changed alarm is {'ON' if ev['shiftAlarm'] else 'off'}.")
    return chr(10).join(out)


def _part_image(session, ev: dict) -> Image.Image | None:
    rid = (ev.get("record") or {}).get("id")
    rec = next((x for x in session.records if x.id == rid), None)
    if rec is None:
        return None
    from .visual import load_media

    return load_media(rec.image_url)


def answer(session, question: str, record_id: str | None = None, lang: str = "en") -> dict:
    ev = _evidence(session, record_id)
    lang = lang if lang in LANGS else "en"
    try:
        if not vlm.available():
            raise FileNotFoundError("model not downloaded")
        text = vlm.answer(question, facts(ev), _part_image(session, ev), lang)
        if not text:
            raise RuntimeError("empty answer")
        mode = f"local VLM ({vlm.MODEL.split('/')[-1]})"
    except Exception as e:  # model missing, GPU out of memory -> grounded template answer
        text = _offline(question, ev, lang)
        mode = f"templates ({type(e).__name__})"
    cites = sorted(set(re.findall(r"\[([^\]]+)\]", text)))
    return {"answer": text, "citations": cites, "mode": mode, "lang": lang, "evidence": ev}


def explain_record(session, rid: str, vision: bool = True) -> dict:
    """'What is wrong with this part?' - the facts are composed from the evidence (instant, cited, cannot be
    hallucinated); the local VLM only adds what each defect close-up looks like, clearly labelled as its view."""
    ev = _evidence(session, rid)
    r = ev.get("record")
    if not r:
        raise KeyError(rid)
    pol = ev["policy"]
    verdict = {"PASS": "Passed", "FAIL": "Rejected", "DOUBT": "Sent to a person", "HOLD": "Held on the belt"}[r["decision"]]
    lines = [f"{verdict}: unusualness {r['score']:.3f} against a pass line of {pol['tau_pass']:.3f} and a fail line of "
             f"{pol['tau_fail']:.3f} [record.score]."]
    regs = r.get("defectRegions") or []
    for g in regs:
        odds = f"; regions like this were real defects {round(100 * g['realOdds'])}% of the time" if g.get("realOdds") is not None else ""
        lines.append(f"{g['id']} at the {_where(g['centroid'])} covers {g['areaPct']}% of the part, {g['severity']}, "
                     f"and looks most like '{g['label']}'{odds} [region {g['id']}].")
    if not regs and r["decision"] in ("FAIL", "DOUBT"):
        lines.append("No single spot stands out: the part is unusual overall [record.defectRegions].")
    if r["decision"] == "DOUBT" and r.get("doubtReason"):
        lines.append(f"I asked a person because: {r['doubtReason'].replace('_', ' ').lower()} [record.doubtReason].")
    out = {"facts": " ".join(lines), "citations": sorted(set(re.findall(r"\[([^\]]+)\]", " ".join(lines)))), "vision": [], "mode": None}
    if vision and regs and vlm.available():
        rec = next(x for x in session.records if x.id == rid)
        from .visual import load_media

        try:
            for g in (rec.regions or [])[:2]:
                crop = load_media(g.get("crop"))
                if crop is None:
                    continue
                txt = vlm.generate([crop.resize((336, 336))],
                                   "This is a close-up of a manufactured part where an anomaly detector flagged something. "
                                   "In one short sentence, describe only what you can see (colour, shape, marks). "
                                   "Do not guess the cause and do not give a verdict.", 60)
                first = re.split(r"(?<=[.!?])\s", txt.strip(), maxsplit=1)[0]
                out["vision"].append({"region": g["id"], "text": first if first.endswith((".", "!", "?")) else first.rsplit(",", 1)[0] + "."})
            out["mode"] = f"local VLM ({vlm.MODEL.split('/')[-1]})"
        except Exception as e:  # GPU busy / out of memory: the facts still stand on their own
            out["mode"] = f"vision unavailable ({type(e).__name__})"
    return out
