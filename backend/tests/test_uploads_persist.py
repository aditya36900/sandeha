"""Bring-your-own-product flow, single-photo 3D relief, active learning, report, and save/restore."""
import shutil
import uuid

import pytest

from sandeha import data, persist, report
from sandeha.engine import Session

pytestmark = pytest.mark.skipif(not data.VISA_ROOT.exists(), reason="VisA not downloaded")


@pytest.fixture(scope="module")
def upload_uid():
    p = data.load_visa("pcb4")
    uid = f"T{uuid.uuid4().hex[:6]}"
    root = data.UPLOAD_ROOT / uid
    for kind, samples in (("good", p.train_good[:20]),
                          ("defect", [s for s in p.test if s.label == 1][:3]),
                          ("test", [s for s in p.test if s.label == 0][:4] + [s for s in p.test if s.label == 1][3:7])):
        (root / kind).mkdir(parents=True, exist_ok=True)
        for i, s in enumerate(samples):
            shutil.copy(s.path, root / kind / f"{i:04d}.jpg")
    yield uid
    shutil.rmtree(root, ignore_errors=True)


def test_uploaded_product_end_to_end(upload_uid):
    s = Session("Upload", upload_uid, n_refs=30)
    assert len(s.ref_samples) == 20 and len(s.known_defects) == 3
    s.genesis()
    assert s.stage == "INTERVIEW"
    assert s.relief and s.twin_cloud["count"] > 10000  # 3D relief from a single photo

    n = 0
    while (smp := s.next_sample()) is not None:
        rec = s.inspect(smp.image(), truth=None)
        assert rec.twin_heat and len(rec.twin_heat) == s.twin_cloud["count"]
        n += 1
    assert n == 8  # every uploaded test photo, in order, then the stream stops

    q = s.review_queue()
    assert all("why" in x for x in q)
    assert len({x["id"] for x in q}) == len(q)

    html = report.build_html(s)
    assert "Risk–coverage report" in html and "<svg" in html or "known truth" in html
    assert report.decisions_csv(s).count("\n") == n + 1

    persist.save(s)
    restored = persist.load_all()[s.id]
    assert len(restored.records) == n
    assert restored.cal.policy.tau_fail == pytest.approx(s.cal.policy.tau_fail)
    r2 = restored.inspect(s.ref_samples[0].image())  # restored session still inspects
    assert r2.decision in ("PASS", "DOUBT", "FAIL")
    persist.forget(s.id)


def test_too_few_reference_photos_is_refused(upload_uid):
    root = data.UPLOAD_ROOT / upload_uid
    tiny = f"{upload_uid}x"
    (data.UPLOAD_ROOT / tiny / "good").mkdir(parents=True)
    for f in sorted((root / "good").glob("*"))[:5]:
        shutil.copy(f, data.UPLOAD_ROOT / tiny / "good" / f.name)
    try:
        with pytest.raises(ValueError):
            Session("Upload", tiny)
    finally:
        shutil.rmtree(data.UPLOAD_ROOT / tiny, ignore_errors=True)
