"""v1 features carried into v2: HOLD verdict, faults, alerts, roles, judge demos, pipeline trace, memory and
forgetting check, analytics, history, passports, telemetry."""
import time

import pytest
from fastapi.testclient import TestClient

from sandeha import data
from sandeha.api import app
from sandeha.station import STATION

pytestmark = pytest.mark.skipif(not data.VISA_ROOT.exists(), reason="VisA not downloaded")
QM = {"X-Role": "QUALITY_MANAGER"}
OP = {"X-Role": "OPERATOR"}


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="module")
def sid(c):
    s = c.post("/api/sessions", json={"source": "VisA", "name": "pcb4", "refs": 20}).json()["id"]
    t = time.time()
    while c.get(f"/api/sessions/{s}").json()["stage"] not in ("INTERVIEW", "LINE"):
        assert time.time() - t < 400
        time.sleep(0.5)
    yield s
    STATION.hold = False
    STATION.faults.clear()


def test_demo_scenarios_drive_the_real_engine(c, sid):
    assert len(c.get("/api/demo").json()) == 8
    good = c.post("/api/demo/1", json={"session": sid}).json()
    assert good["decision"] in ("PASS", "DOUBT")
    bad = c.post("/api/demo/2", json={"session": sid}).json()
    assert bad["decision"] in ("FAIL", "DOUBT")
    novel = c.post("/api/demo/3", json={"session": sid}).json()
    assert novel["decision"] in ("DOUBT", "FAIL")
    learn = c.post("/api/demo/7", json={"session": sid}, headers=QM).json()
    assert "Two-person" in learn["message"]


def test_hold_and_faults_give_hold_verdicts(c, sid):
    assert c.post("/api/station/hold", json={"on": True, "reason": "test stop"}, headers=OP).json()["hold"]
    r = c.post("/api/demo/1", json={"session": sid}).json()
    assert r["decision"] == "HOLD" and "Emergency HOLD" in r["message"]
    assert c.post("/api/station/hold", json={"on": False}, headers=OP).status_code == 403  # an operator cannot release
    c.post("/api/station/hold", json={"on": False}, headers=QM)
    cam = c.post("/api/demo/6", json={"session": sid}).json()
    assert cam["decision"] == "HOLD" and "dark" in cam["message"]
    alerts = c.get("/api/alerts?open_only=true").json()
    assert any(a["category"] == "HARDWARE" for a in alerts)
    c.post("/api/station/restore", headers=QM)
    assert not c.get("/api/station").json()["faults"]
    assert not any(a["category"] == "HARDWARE" for a in c.get("/api/alerts?open_only=true").json())


def test_trace_memory_forgetting(c, sid):
    rec = c.get(f"/api/sessions/{sid}/records").json()[-1]
    tr = c.get(f"/api/sessions/{sid}/trace/{rec['id']}").json()
    assert [s["key"] for s in tr["stages"]] == ["see", "quality", "understand", "compare", "components", "locate", "doubt", "decide", "learn"]
    mem = c.get(f"/api/sessions/{sid}/memory").json()
    assert mem["normal"]["patchMemories"] > 1000 and mem["forgetting"]
    f = c.post(f"/api/sessions/{sid}/forgetting").json()
    assert f["latest"]["goods"] == f["baseline"]["goods"]
    assert f["latest"]["goodsPassed"] >= f["baseline"]["goodsPassed"] - 1  # learning did not break what it knew


def test_analytics_history_passport_telemetry_roles(c, sid):
    ov = c.get("/api/overview").json()
    assert ov["totals"]["parts"] >= 5 and len(ov["trend"]) == 30
    an = c.get(f"/api/analytics?session={sid}").json()
    assert "pareto" in an and "timeline" in an
    h = c.get("/api/history?decision=HOLD").json()
    assert h["total"] >= 1 and all(r["decision"] == "HOLD" for r in h["rows"])
    p = c.get(f"/api/passport/{h['rows'][0]['id']}").json()
    assert p["record"]["routing"] == "HOLD_ON_BELT" and p["record"]["quality"]
    t = c.get("/api/telemetry").json()
    assert t["measured"]["cpuPercent"] >= 0 and t["measured"]["partsInspected"] >= 5
    assert c.post("/api/system/reset?reseed=false", headers=OP).status_code == 403
    assert c.post(f"/api/sessions/{sid}/settings", json={"budget": 0.05}, headers=OP).status_code == 403
    s = c.post(f"/api/sessions/{sid}/settings", json={"budget": 0.05, "falseRejectGuarantee": 0.05}, headers=QM).json()
    assert s["budget"] == 0.05 and s["policy"]["alpha_fr"] == 0.05
    assert any(e["action"] == "product.settings" for e in c.get("/api/audit").json())
    assert c.get("/api/outbox").json()  # decisions were published to the line
