import copy
from types import SimpleNamespace

from sandeha import certificate
from sandeha.trust import Calibrator


def _fake_session():
    recs = [SimpleNamespace(id=f"P{i}", decision="PASS", score=0.1, review={}, ghost=False) for i in range(5)]
    return SimpleNamespace(records=recs, cal=Calibrator([0.1] * 30, [0.3] * 10), plant="Plant A", source="VisA",
                           name="pcb4", guard=SimpleNamespace(alarmed=False))


def test_certificate_verifies_and_detects_tampering():
    doc = certificate.issue(_fake_session(), "http://localhost:8000/")
    assert certificate.verify(doc) == (True, True)
    forged = copy.deepcopy(doc)
    forged["claim"]["autoPassed"] = 999
    assert certificate.verify(forged)[0] is False
    edited = copy.deepcopy(doc)
    edited["chain"][-1]["hash"] = "0" * 64
    assert certificate.verify(edited)[1] is False
