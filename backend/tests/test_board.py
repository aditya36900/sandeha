"""Electronics: component map, per-component diagnosis, fault lab, scans carry component verdicts."""
import time

import pytest
from fastapi.testclient import TestClient

from sandeha import data
from sandeha.api import SESSIONS, app

pytestmark = pytest.mark.skipif(not data.VISA_ROOT.exists(), reason="VisA not downloaded")


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="module")
def sid(c):
    s = c.post("/api/sessions", json={"source": "VisA", "name": "pcb4", "refs": 30}).json()["id"]
    t = time.time()
    while c.get(f"/api/sessions/{s}/board").json().get("status") != "ready":
        assert time.time() - t < 600, "component map not built in time"
        time.sleep(1)
    return s


def test_catalog_is_electronics_only(c):
    names = [x["name"] for x in c.get("/api/catalog").json()]
    assert names and all(n.startswith("pcb") for n in names)


def test_board_map_has_typed_components_with_3d_boxes(c, sid):
    b = c.get(f"/api/sessions/{sid}/board").json()
    comps = b["components"]
    assert len(comps) >= 10
    assert {"IC", "resistor"} <= set(b["kinds"])
    assert sum(x["box3d"] is not None for x in comps) >= 0.8 * len(comps)  # pinned on the relief
    assert b["classifier"]["holdoutAccuracy"] > 0.8


def test_fault_lab_flags_the_right_component(c, sid):
    b = c.get(f"/api/sessions/{sid}/board").json()
    target = max((x for x in b["components"] if x["kind"] in ("resistor", "capacitor", "IC")), key=lambda x: x["areaPct"])["id"]
    flagged = 0
    for _ in range(3):  # planted on a random held-out good board each time
        r = c.post(f"/api/sessions/{sid}/faultlab", json={"component": target, "kind": "missing"}).json()
        assert r["synthetic"] and r["truth"] is None  # never pollutes the real metrics
        flagged += any(f["id"] == target for f in r["board"]["faults"])
    assert flagged >= 2
    assert c.post(f"/api/sessions/{sid}/faultlab", json={"component": target, "kind": "nonsense"}).status_code == 409


def test_scans_carry_component_verdicts(c, sid):
    lot = c.post(f"/api/sessions/{sid}/lot", json={"n": 6}).json()["lot"]
    recs = [c.post(f"/api/sessions/{sid}/scan", json={"token": p["token"]}).json() for p in lot]
    assert all(r["board"] and r["board"]["checked"] >= 10 for r in recs if r["decision"] != "HOLD")
    s = SESSIONS[sid]
    tr = c.get(f"/api/sessions/{sid}/trace/{recs[0]['id']}").json()
    assert any(st["key"] == "components" for st in tr["stages"])
    assert s.board is not None
