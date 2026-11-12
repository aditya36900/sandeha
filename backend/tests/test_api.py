"""End-to-end through the HTTP API on a real VisA product (needs the dataset; a couple of minutes on GPU)."""
import time

import pytest
from fastapi.testclient import TestClient

from sandeha import data
from sandeha.api import app

pytestmark = pytest.mark.skipif(not data.VISA_ROOT.exists(), reason="VisA not downloaded")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _wait(c, sid, pred, timeout=400):
    t = time.time()
    while time.time() - t < timeout:
        s = c.get(f"/api/sessions/{sid}").json()
        if pred(s):
            return s
        time.sleep(0.5)
    raise AssertionError("timeout")


def test_full_flow(client):
    c = client
    sid = c.post("/api/sessions", json={"source": "VisA", "name": "capsules", "refs": 20}).json()["id"]
    s = _wait(c, sid, lambda s: s["stage"] in ("INTERVIEW", "LINE"))
    assert s["policy"]["tau_pass"] <= s["policy"]["tau_fail"]
    assert s["questions"], "the AI must ask before inspecting"

    st = c.get(f"/api/sessions/{sid}/state").json()  # page-refresh rehydration
    assert len(st["photos"]) == 20 and st["imagined"]

    c.post(f"/api/sessions/{sid}/stream", json={"n": 30, "defectRate": 0.3, "delay": 0})
    _wait(c, sid, lambda s: s["records"] >= 30)
    recs = c.get(f"/api/sessions/{sid}/records").json()
    assert all(r["decision"] in ("PASS", "FAIL", "DOUBT") and r["explanation"] for r in recs)

    # two-person rule: one reviewer is never enough to teach the AI
    target = next(r for r in recs if not r["ghost"])
    url = f"/api/sessions/{sid}/records/{target['id']}/review"
    r1 = c.post(url, json={"verdict": "GOOD", "reviewer": "A", "role": "INSPECTOR"}).json()
    assert "second" in r1["status"]
    r2 = c.post(url, json={"verdict": "GOOD", "reviewer": "B", "role": "QUALITY_MANAGER"}).json()
    assert "Two-person" in r2["status"]
    assert c.post(url, json={"verdict": "GOOD", "reviewer": "C", "role": "OPERATOR"}).status_code == 403

    # adapting to new conditions must never loosen the fail line
    before = c.get(f"/api/sessions/{sid}").json()["policy"]["tau_fail"]
    c.post(f"/api/sessions/{sid}/conditions", json={"preset": "camera_bumped"})
    assert c.post(f"/api/sessions/{sid}/preview", json={"rotation": 7}).json()["after"].startswith("data:image")
    c.post(f"/api/sessions/{sid}/adapt", json={"n": 5})
    assert c.get(f"/api/sessions/{sid}").json()["policy"]["tau_fail"] == pytest.approx(before)

    t = c.get(f"/api/sessions/{sid}/trust").json()
    assert t["rows"] and all(0 <= r["reviewRate"] <= 1 for r in t["rows"])

    cert = c.post(f"/api/sessions/{sid}/certificate").json()
    assert "Signature valid" in c.get("/verify/" + cert["claim"]["certificate"]).text

    assert c.post(f"/api/sessions/{sid}/ask", json={"question": "Why?", "lang": "en"}).json()["answer"]
    assert c.get("/api/galaxy").json()["points"]
