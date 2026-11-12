"""Control-room overview, defect analytics, inspection history and digital product passports
(v1 features, now computed from real inspection records)."""
from __future__ import annotations

import time
from collections import Counter, defaultdict

from .station import STATION

DECISIONS = ("PASS", "FAIL", "DOUBT", "HOLD")


def _known(recs):
    return [r for r in recs if r.truth is not None and not r.ghost]


def overview(sessions) -> dict:
    recs = [r for s in sessions for r in s.records if not r.ghost]
    counts = Counter(r.decision for r in recs)
    known = _known(recs)
    defects = [r for r in known if r.truth == 1]
    esc = sum(r.decision == "PASS" for r in defects)
    esc_naive = sum(r.naive_decision == "PASS" for r in defects)
    lat = sorted(r.latency_ms for r in recs[-300:] if r.latency_ms)
    # throughput: parts per minute over the last 30 minutes
    now = time.time()
    per_min = defaultdict(lambda: Counter())
    for r in recs:
        try:
            t = time.mktime(time.strptime(r.created, "%Y-%m-%d %H:%M:%S"))
        except Exception:
            continue
        m = int((now - t) // 60)
        if m < 30:
            per_min[29 - m][r.decision] += 1
    trend = [{"minute": i - 29, **{d: per_min[i][d] for d in DECISIONS}} for i in range(30)]
    s_cost = STATION.settings
    cost = lambda e, fr, rv: e * s_cost["costPerEscape"] + fr * s_cost["costPerFalseReject"] + rv * s_cost["costPerReview"]  # noqa: E731
    fr = sum(r.decision == "FAIL" and r.truth == 0 for r in known)
    fr_naive = sum(r.naive_decision == "FAIL" and r.truth == 0 for r in known)
    products = []
    for s in sessions:
        sr = [r for r in s.records if not r.ghost]
        c = Counter(r.decision for r in sr)
        products.append({"session": s.id, "name": s.product.name, "source": s.source, "plant": s.plant, "stage": s.stage,
                         "parts": len(sr), **{d.lower(): c[d] for d in DECISIONS}, "alarm": bool(getattr(s, "guard", None) and s.guard.alarmed),
                         "thumb": (getattr(s, "thumbs", None) or [None])[0]})
    return {
        "totals": {"parts": len(recs), **{d.lower(): counts[d] for d in DECISIONS},
                   "reviewRate": counts["DOUBT"] / max(len(recs), 1), "holdRate": counts["HOLD"] / max(len(recs), 1)},
        "measured": {"defectsSeen": len(defects), "escapes": esc, "escapesTypicalAI": esc_naive,
                     "falseRejects": fr, "falseRejectsTypicalAI": fr_naive,
                     "cost": cost(esc, fr, counts["DOUBT"]), "costTypicalAI": cost(esc_naive, fr_naive, 0)},
        "latencyMsP50": lat[len(lat) // 2] if lat else None,
        "trend": trend,
        "recent": [_row(r, s) for s in sessions for r in s.records[-8:]][-10:],
        "products": products,
        "station": STATION.public(),
        "alerts": [a.__dict__ for a in STATION.alerts if not a.resolved][-8:],
    }


def _row(r, s) -> dict:
    return {"id": r.id, "session": s.id, "product": s.product.name, "decision": r.decision, "reason": r.doubt_reason or r.hold_reason,
            "score": r.score, "truth": r.truth, "defectType": r.defect_type, "image": r.image_url, "created": r.created,
            "review": r.review.get("final"), "naive": r.naive_decision, "latencyMs": r.latency_ms}


def analytics(sessions, session_id: str | None = None) -> dict:
    ss = [s for s in sessions if session_id in (None, s.id)]
    recs = [r for s in ss for r in s.records if not r.ghost]
    known = _known(recs)
    # Pareto of defect types: what each inspector did with every truly defective part
    types = defaultdict(lambda: {"caught": 0, "asked": 0, "escaped": 0, "escapedTypicalAI": 0, "held": 0})
    for r in known:
        if r.truth != 1:
            continue
        for t in (r.defect_type or "defect").split(","):
            t = t.strip() or "defect"
            k = types[t]
            k["caught" if r.decision == "FAIL" else "asked" if r.decision == "DOUBT" else "held" if r.decision == "HOLD" else "escaped"] += 1
            k["escapedTypicalAI"] += r.naive_decision == "PASS"
    pareto = sorted(({"type": t, **v, "total": sum(v[x] for x in ("caught", "asked", "escaped", "held"))} for t, v in types.items()),
                    key=lambda x: -x["total"])
    # where on the part the unusual regions sit (flagged parts only)
    spots = [{"x": r.hotspot["x"], "y": r.hotspot["y"], "decision": r.decision, "id": r.id, "session": r.session}
             for r in recs if r.decision in ("FAIL", "DOUBT")]
    reasons = Counter(r.doubt_reason or "unspecified" for r in recs if r.decision == "DOUBT")
    holds = Counter((r.hold_reason or "").split(" (")[0] for r in recs if r.decision == "HOLD")
    # decisions over time, in blocks of 10 parts
    blocks = []
    for i in range(0, len(recs), 10):
        c = Counter(r.decision for r in recs[i:i + 10])
        blocks.append({"block": i // 10 + 1, **{d: c[d] for d in DECISIONS}})
    changed_ids = {r.id for r in recs if any(v not in (0, 0.0, 1, 1.0) for v in (r.conditions or {}).values())}
    changed = [r for r in recs if r.id in changed_ids]
    def rate(lst, d):
        return sum(r.decision == d for r in lst) / max(len(lst), 1)
    normal = [r for r in recs if r.id not in changed_ids]
    cond = {"normal": {d: rate(normal, d) for d in DECISIONS}, "changed": {d: rate(changed, d) for d in DECISIONS},
            "nNormal": len(normal), "nChanged": len(changed)}
    product_image = (getattr(ss[0], "thumbs", None) or [None])[0] if len(ss) == 1 else None
    return {"pareto": pareto, "spots": spots, "doubtReasons": dict(reasons), "holdReasons": dict(holds),
            "timeline": blocks, "conditions": cond, "productImage": product_image,
            "forecast": ss[0].forecast if len(ss) == 1 else None}


def history(sessions, decision=None, session=None, reason=None, truth=None, q=None, offset=0, limit=50) -> dict:
    rows = []
    for s in sessions:
        if session and s.id != session:
            continue
        for r in s.records:
            if r.ghost:
                continue
            if decision and r.decision != decision:
                continue
            if reason and (r.doubt_reason or r.hold_reason or "") != reason:
                continue
            if truth == "defect" and r.truth != 1 or truth == "good" and r.truth != 0 or truth == "unknown" and r.truth is not None:
                continue
            if q and q.lower() not in f"{r.id} {s.product.name} {r.defect_type or ''} {r.explanation}".lower():
                continue
            rows.append(_row(r, s))
    rows.sort(key=lambda x: x["created"], reverse=True)
    return {"total": len(rows), "rows": rows[offset:offset + limit]}


def passport(sessions, rid: str) -> dict:
    from . import certificate

    for s in sessions:
        r = next((x for x in s.records if x.id == rid), None)
        if r is None:
            continue
        certs = [c for c in certificate.STORE.values() if any(x["id"] == rid for x in c["chain"])]
        link = None
        if certs:
            c = certs[-1]
            link = {"certificate": c["claim"]["certificate"], "hash": next(x["hash"] for x in c["chain"] if x["id"] == rid),
                    "verifyUrl": c["verifyUrl"]}
        return {"record": r.to_dict(heat=False), "product": s.product.name, "source": s.source, "plant": s.plant,
                "session": s.id, "policy": s.cal.policy.to_dict(), "certificate": link,
                "station": STATION.name}
    raise KeyError(rid)
