"""Live scan: unlabelled lot, named defect regions with 3D anchors, grounded explanations, honest blind spots."""
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from sandeha import data, regions
from sandeha.api import SESSIONS, app


def test_keep_rule_drops_weak_far_regions():
    heat = np.zeros((256, 256), np.float32)
    heat[40:60, 40:60] = 1.0   # the real defect
    heat[200:215, 200:215] = 0.5  # above the pass line, but only half as unusual as the worst spot
    c = regions.candidates(heat, tau_pass=0.3)
    assert len(c) == 1 and c[0][0][50, 50]
    img = Image.new("RGB", (256, 256), (90, 90, 90))
    r = regions.find_regions(heat, img, None, 0.3, 0.6, library=None)
    assert r[0]["severity"] == "critical" and abs(r[0]["centroid"][0] - 50 / 256) < 0.02


pytestmark_visa = pytest.mark.skipif(not data.VISA_ROOT.exists(), reason="VisA not downloaded")


@pytest.fixture(scope="module")
def c():
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="module")
def sid(c):
    if not data.VISA_ROOT.exists():
        pytest.skip("VisA not downloaded")
    s = c.post("/api/sessions", json={"source": "VisA", "name": "pcb1", "refs": 20}).json()["id"]
    t = time.time()
    while c.get(f"/api/sessions/{s}").json()["stage"] not in ("INTERVIEW", "LINE"):
        assert time.time() - t < 400
        time.sleep(0.5)
    return s


@pytestmark_visa
def test_lot_is_unlabelled_and_scans_find_regions(c, sid):
    lot = c.post(f"/api/sessions/{sid}/lot", json={"n": 16}).json()["lot"]
    assert len(lot) == 16 and all(set(p) == {"token", "thumb"} for p in lot)  # no truth leaves the server
    flagged = []
    for p in lot:
        r = c.post(f"/api/sessions/{sid}/scan", json={"token": p["token"]}).json()
        assert "regions" in r["stage_ms"]
        if r["decision"] in ("FAIL", "DOUBT"):
            flagged.append(r)
    assert c.post(f"/api/sessions/{sid}/scan", json={"token": lot[0]["token"]}).status_code == 404  # scanned once only
    with_regions = [r for r in flagged if r["regions"]]
    assert with_regions, "no flagged part produced a defect region"
    g = with_regions[0]["regions"][0]
    assert g["label"] and g["severity"] in ("minor", "major", "critical") and g["crop"].startswith("/media/")
    assert g["anchor"] is not None and len(g["anchor"]) == 3  # pinned on the 3D relief
    ex = c.post(f"/api/sessions/{sid}/records/{with_regions[0]['id']}/explain?vision=false").json()
    assert "[record.score]" in ex["facts"] and "region R1" in ex["citations"]


@pytestmark_visa
def test_blind_spots_are_measured_on_the_part_only(c, sid):
    s = SESSIONS[sid]
    res = s.blind_spots(grid=5, kind="scratch", verify=False)
    states = {x["state"] for x in res["cells"]}
    assert res["regions"] >= 6 and states <= {"sharp", "medium", "large", "blind", "untestable"}
    assert res["blindCells"] < res["regions"]  # leave-one-out scoring: large planted scratches are caught
    m = s.part_mask(s.ref_images[0])
    assert 0.05 < m.mean() < 0.95
