"""Station-level routes carried over from v1: overview, alerts, hardware, history, passports, pipeline
trace, memory, analytics, settings, roles, judge demo scenarios, reset."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict

import numpy as np
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from . import analytics, persist
from .data import DATA_ROOT
from .engine import SESSIONS
from .events import bus
from .shift import PRESETS
from .station import FAULTS, ROLES, STATION

router = APIRouter()
NAMES = {"OPERATOR": "Line operator", "INSPECTOR": "Rajesh K.", "QUALITY_MANAGER": "Sunita M.", "ADMIN": "Station admin"}
STATION_FILE = DATA_ROOT / "station.json"


def role_of(x_role: str | None) -> str:
    r = (x_role or "QUALITY_MANAGER").upper()
    return r if r in ROLES else "OPERATOR"


def require(x_role: str | None, *allowed: str) -> str:
    r = role_of(x_role)
    if r not in allowed:
        raise HTTPException(403, f"A {r.replace('_', ' ').lower()} cannot do this; it needs: "
                                 + ", ".join(a.replace('_', ' ').lower() for a in allowed))
    return r


def S(sid: str):
    s = SESSIONS.get(sid)
    if not s:
        raise HTTPException(404, f"Unknown product line {sid}")
    return s


def _ready():
    return [s for s in SESSIONS.values() if s.stage in ("INTERVIEW", "LINE")]


# ------------------------------------------------------------------ persistence of station state
def save_station() -> None:
    try:
        STATION_FILE.write_text(json.dumps({"name": STATION.name, "settings": STATION.settings,
                                            "alerts": [asdict(a) for a in STATION.alerts[-300:]],
                                            "audit": STATION.audit[-1000:]}))
    except Exception:
        pass


def load_station() -> None:
    from .station import Alert

    if not STATION_FILE.exists():
        return
    try:
        d = json.loads(STATION_FILE.read_text())
        STATION.name = d.get("name", STATION.name)
        STATION.settings.update(d.get("settings", {}))
        STATION.alerts = [Alert(**a) for a in d.get("alerts", [])]
        STATION.audit = d.get("audit", [])
    except Exception:
        pass


# ------------------------------------------------------------------ station, hold, faults, telemetry
@router.get("/api/station")
def station():
    return STATION.public()


class HoldIn(BaseModel):
    on: bool
    reason: str = ""


@router.post("/api/station/hold")
def hold(body: HoldIn, x_role: str | None = Header(None)):
    r = role_of(x_role)
    if not body.on:  # releasing a stop needs someone accountable
        require(x_role, "INSPECTOR", "QUALITY_MANAGER", "ADMIN")
    return STATION.set_hold(body.on, body.reason or "Manual emergency stop", NAMES[r])


class FaultIn(BaseModel):
    fault: str


@router.post("/api/station/fault")
def fault(body: FaultIn, x_role: str | None = Header(None)):
    if body.fault not in FAULTS:
        raise HTTPException(422, f"fault must be one of {FAULTS}")
    return STATION.inject(body.fault, NAMES[role_of(x_role)])


@router.post("/api/station/restore")
def restore(x_role: str | None = Header(None)):
    r = require(x_role, "INSPECTOR", "QUALITY_MANAGER", "ADMIN")
    return STATION.restore(NAMES[r])


@router.get("/api/telemetry")
def telemetry():
    return STATION.telemetry(list(SESSIONS.values()))


@router.get("/api/outbox")
def outbox(limit: int = 60):
    return list(reversed(STATION.outbox[-limit:]))


@router.get("/api/audit")
def audit(limit: int = 200):
    return list(reversed(STATION.audit[-limit:]))


# ------------------------------------------------------------------ alerts
@router.get("/api/alerts")
def alerts(open_only: bool = False):
    a = [asdict(x) for x in STATION.alerts if not (open_only and x.resolved)]
    return list(reversed(a))


@router.post("/api/alerts/{aid}/ack")
def ack(aid: str, x_role: str | None = Header(None)):
    try:
        return asdict(STATION.ack(aid, NAMES[role_of(x_role)]))
    except KeyError:
        raise HTTPException(404, "Unknown alert")


@router.post("/api/alerts/{aid}/resolve")
def resolve(aid: str, x_role: str | None = Header(None)):
    r = require(x_role, "INSPECTOR", "QUALITY_MANAGER", "ADMIN")
    try:
        return asdict(STATION.resolve(aid, NAMES[r]))
    except KeyError:
        raise HTTPException(404, "Unknown alert")


# ------------------------------------------------------------------ overview, analytics, history, passport
@router.get("/api/overview")
def overview():
    return analytics.overview(list(SESSIONS.values()))


@router.get("/api/analytics")
def analytics_route(session: str | None = None):
    return analytics.analytics(list(SESSIONS.values()), session)


@router.get("/api/history")
def history(decision: str | None = None, session: str | None = None, reason: str | None = None,
            truth: str | None = None, q: str | None = None, offset: int = 0, limit: int = 50):
    return analytics.history(list(SESSIONS.values()), decision, session, reason, truth, q, offset, limit)


@router.get("/api/history.csv")
def history_csv():
    import csv
    import io

    from fastapi.responses import Response

    rows = analytics.history(list(SESSIONS.values()), limit=100000)["rows"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else ["id"])
    w.writeheader()
    w.writerows(rows)
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="sandeha-history.csv"'})


@router.get("/api/passport/{rid}")
def passport(rid: str):
    try:
        return analytics.passport(list(SESSIONS.values()), rid)
    except KeyError:
        raise HTTPException(404, "Unknown part")


@router.get("/api/sessions/{sid}/trace/{rid}")
def trace(sid: str, rid: str):
    try:
        return S(sid).trace(rid)
    except KeyError:
        raise HTTPException(404, "Unknown part")


# ------------------------------------------------------------------ memory + product settings
@router.get("/api/sessions/{sid}/memory")
def memory(sid: str):
    return S(sid).memory_summary()


@router.post("/api/sessions/{sid}/forgetting")
def forgetting(sid: str, x_role: str | None = Header(None)):
    s = S(sid)
    label = f"Check after {len(getattr(s, 'adaptations', []))} adaptation(s), {len(s.learned_defects)} learned defect(s)"
    out = s.forgetting_check(label)
    STATION.log(NAMES[role_of(x_role)], role_of(x_role), "forgetting.check", sid, out["latest"])
    return out


class ProductSettingsIn(BaseModel):
    budget: float | None = None
    falseRejectGuarantee: float | None = None
    autopilot: bool | None = None


@router.post("/api/sessions/{sid}/settings")
def product_settings(sid: str, body: ProductSettingsIn, x_role: str | None = Header(None)):
    r = require(x_role, "QUALITY_MANAGER", "ADMIN")
    s = S(sid)
    with s.lock:
        if body.autopilot is not None:
            s.autopilot = body.autopilot
        if body.budget is not None:
            s.budget = float(np.clip(body.budget, 0.01, 0.5))
        if body.falseRejectGuarantee is not None:
            a = float(np.clip(body.falseRejectGuarantee, 0.005, 0.2))
            from .trust import Calibrator

            defects = np.concatenate([s.known_scores, s.imagined_scores])
            s.cal = Calibrator(s.loo, defects, alpha_fr=a, beta=s.cal.policy.beta, budget=getattr(s, "budget", 0.10))
    STATION.log(NAMES[r], r, "product.settings", sid, body.model_dump(exclude_none=True))
    bus.publish("trust.policy", {"session": sid, "policy": s.cal.policy.to_dict()})
    return {"policy": s.cal.policy.to_dict(), "budget": getattr(s, "budget", 0.10), "autopilot": getattr(s, "autopilot", True)}


# ------------------------------------------------------------------ station settings + reset
class StationSettingsIn(BaseModel):
    name: str | None = None
    settings: dict | None = None


@router.get("/api/settings")
def get_settings():
    from . import vlm

    local = vlm.available()
    return {"name": STATION.name, "settings": STATION.settings, "roles": list(ROLES), "names": NAMES,
            "copilot": f"local {vlm.MODEL} on this station (no cloud)" if local else "templates (local model not downloaded)",
            "models": {"anomaly": "facebook/dinov2-small (frozen, patch memory)", "regionNames": "openai/clip-vit-base-patch16 + labelled-defect fingerprints",
                       "copilot": vlm.MODEL if local else None, "depth": "Depth Anything V2 Small"}}


@router.put("/api/settings")
def put_settings(body: StationSettingsIn, x_role: str | None = Header(None)):
    r = require(x_role, "QUALITY_MANAGER", "ADMIN")
    if body.name:
        STATION.name = body.name[:60]
    if body.settings:
        for k, v in body.settings.items():
            if k in STATION.settings:
                STATION.settings[k] = type(STATION.settings[k])(v)
    STATION.log(NAMES[r], r, "station.settings", detail=body.model_dump(exclude_none=True))
    save_station()
    bus.publish("station", STATION.public())
    return get_settings()


@router.post("/api/system/reset")
def reset(x_role: str | None = Header(None), reseed: bool = True):
    r = require(x_role, "ADMIN", "QUALITY_MANAGER")
    for sid in list(SESSIONS):
        SESSIONS.pop(sid, None)
        persist.forget(sid)
    STATION.alerts.clear()
    STATION.faults.clear()
    STATION.hold = False
    STATION.log(NAMES[r], r, "system.reset", detail={"reseed": reseed})
    bus.publish("reset", {})
    if reseed:
        threading.Thread(target=_seed, daemon=True).start()
    return {"ok": True, "reseeding": reseed}


def _seed() -> None:
    from .engine import Session

    for src, name, n, rate in (("VisA", "pcb4", 40, 0.15), ("VisA", "pcb3", 30, 0.15)):
        s = Session(src, name)
        SESSIONS[s.id] = s
        s.genesis()
        rng = np.random.default_rng(1)
        for _ in range(n):
            smp = s.next_sample(rate, rng)
            s.inspect(smp.image(), truth=smp.label, defect_type=smp.defect_type, ghost=bool(rng.random() < 0.08))
    bus.publish("sessions.restored", {"count": len(SESSIONS)})


# ------------------------------------------------------------------ judge demo scenarios
DEMOS = [
    {"n": 1, "title": "A good part passes on its own", "expect": "PASS", "goTo": "line"},
    {"n": 2, "title": "A real defect is rejected", "expect": "FAIL", "goTo": "line"},
    {"n": 3, "title": "Something never seen: it asks a person", "expect": "DOUBT", "goTo": "line"},
    {"n": 4, "title": "Someone bumps the camera: it notices", "expect": "alarm", "goTo": "chaos"},
    {"n": 5, "title": "A brand-new product from 20 photos", "expect": "learn", "goTo": "choose"},
    {"n": 6, "title": "The camera dies: nothing is decided blind", "expect": "HOLD", "goTo": "hardware"},
    {"n": 7, "title": "Two people teach it; it remembers", "expect": "learn", "goTo": "memory"},
    {"n": 8, "title": "Too many doubts: the line raises an alert", "expect": "alert", "goTo": "overview"},
]


@router.get("/api/demo")
def demos():
    return DEMOS


class DemoIn(BaseModel):
    session: str | None = None


@router.post("/api/demo/{n}")
def run_demo(n: int, body: DemoIn, x_role: str | None = Header(None)):
    d = next((x for x in DEMOS if x["n"] == n), None)
    if d is None:
        raise HTTPException(404, "Unknown scenario")
    if n == 5:
        return {**d, "message": "Open 'Bring your own product' and drop 20 good photos."}
    cands = [s for s in _ready() if s.source in ("VisA", "Upload")] or _ready()
    s = SESSIONS.get(body.session) if body.session in SESSIONS else (cands[0] if cands else None)
    if s is None:
        raise HTTPException(409, "Open a product line first (for example pcb4) and let it finish learning.")
    STATION.log(NAMES[role_of(x_role)], role_of(x_role), "demo", s.id, {"scenario": n})
    if n in (1, 2, 3):
        s.conditions = type(s.conditions)()  # never touches an emergency HOLD
        img, truth, dt = s.demo_image({1: "good", 2: "defect", 3: "novel"}[n])
        rec = s.inspect(img, truth=truth, defect_type=dt)
        return {**d, "session": s.id, "record": rec.id, "decision": rec.decision, "message": rec.explanation}
    if n == 4:
        s.set_conditions(PRESETS["camera_bumped"].__dict__)
        _bg_stream(s, 22, 0.05)
        return {**d, "session": s.id, "message": "Camera bumped; 22 parts are running. Watch the evidence curve."}
    if n == 6:
        STATION.inject("camera", NAMES[role_of(x_role)])
        recs = [s.inspect(s.demo_image("good")[0]) for _ in range(3)]
        return {**d, "session": s.id, "record": recs[-1].id, "decision": recs[-1].decision,
                "message": recs[-1].explanation}
    if n == 7:
        q = s.review_queue()
        if not q:
            img, truth, dt = s.demo_image("novel")
            s.inspect(img, truth=truth, defect_type=dt)
            q = s.review_queue()
        if q:
            rid = q[0]["id"]
        else:  # nothing in doubt: teach it from the most recent part instead
            recent = [r for r in s.records if not r.ghost and r.review.get("final") not in ("GOOD", "DEFECT")]
            if not recent:
                raise HTTPException(409, "Inspect a part first.")
            rid = recent[-1].id
        rec = next(r for r in s.records if r.id == rid)
        verdict = "DEFECT" if rec.truth == 1 else "GOOD"
        s.review(rid, verdict, NAMES["INSPECTOR"], "INSPECTOR")
        out = s.review(rid, verdict, NAMES["QUALITY_MANAGER"], "QUALITY_MANAGER")
        return {**d, "session": s.id, "record": rid, "message": out["status"]}
    if n == 8:
        s.autopilot = False
        def run():
            rng = np.random.default_rng(int(time.time()))
            for _ in range(30):
                smp = s.next_sample(0.5, rng)
                if smp is None:
                    break
                s.inspect(smp.image(), truth=smp.label if smp.label >= 0 else None, defect_type=smp.defect_type)
            s.autopilot = True
        threading.Thread(target=run, daemon=True).start()
        return {**d, "session": s.id, "message": "30 defect-heavy parts with the budget autopilot off."}
    raise HTTPException(404, "Unknown scenario")


def _bg_stream(s, n, rate):
    def run():
        rng = np.random.default_rng(int(time.time()))
        for _ in range(n):
            smp = s.next_sample(rate, rng)
            if smp is None:
                break
            s.inspect(smp.image(), truth=smp.label if smp.label >= 0 else None, defect_type=smp.defect_type)
            time.sleep(0.1)
    threading.Thread(target=run, daemon=True).start()
