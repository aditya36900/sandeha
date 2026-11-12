import sys, time; sys.path.insert(0, ".")
import numpy as np
from sandeha.engine import Session, SESSIONS
from sandeha import certificate, galaxy, copilot
from sandeha.shift import PRESETS
t=time.time()
a = Session("VisA", "capsules", seed=0, plant="Plant A"); SESSIONS[a.id]=a; a.genesis()
print("genesis %.1fs" % (time.time()-t), "questions:", [q["type"] for q in a.questions], "policy tau_pass/fail", round(a.cal.policy.tau_pass,4), round(a.cal.policy.tau_fail,4))
for q in a.questions:
    a.answer(q["id"], q["options"][0])
rng = np.random.default_rng(1)
for i in range(30):
    s = a.next_sample(0.3, rng); a.inspect(s.image(), truth=s.label, defect_type=s.defect_type, ghost=(i % 9 == 0))
perf = a.performance(); print("stream:", perf["ours"], "naive:", perf["naive"], "doubt reasons:", sorted({r.doubt_reason for r in a.records if r.doubt_reason}))
d = next(r for r in a.records if r.truth == 1 and not r.ghost)
print("review1:", a.review(d.id, "DEFECT", "Rajesh", "INSPECTOR")["status"])
print("review2:", a.review(d.id, "DEFECT", "Sunita", "QUALITY_MANAGER")["status"])
a.set_conditions(PRESETS["camera_bumped"].__dict__)
for i in range(25):
    s = a.next_sample(0.0, rng); r = a.inspect(s.image(), truth=s.label)
print("after camera bump: alarm", a.guard.alarmed, "last decisions", [r.decision for r in a.records[-5:]], [r.doubt_reason for r in a.records[-3:]])
print(a.adapt(5)["message"])
tc = a.trust_curve(); print("trust rows", [(round(r['targetEscape'],3), round(r['reviewRate'],3), int(r['ppm'])) for r in tc["rows"][:4]], "naive ppm", int(tc["naive"]["ppm"]))
cert = certificate.issue(a, "http://localhost:8000/"); ok = certificate.verify(cert); print("certificate", cert["claim"]["certificate"], "verify", ok)
b = Session("VisA", "capsules", seed=1, plant="Plant B"); SESSIONS[b.id]=b; b.genesis()
print("hive share ->", b.receive_fingerprints(a.share_fingerprints()))
s = next(x for x in b.eval_pool if x.label == 1 and x.defect_type == d.defect_type)
rb = b.inspect(s.image(), truth=1, defect_type=s.defect_type); print("plant B on same defect type:", rb.decision, rb.explanation[:90])
g = galaxy.build([a, b]); print("galaxy points", len(g["points"]))
print("copilot:", copilot.answer(a, "Why did you reject this part?", d.id)["answer"][:200])
m = Session("MAD-Sim", "02Unicorn", seed=0); SESSIONS[m.id]=m; t=time.time(); m.genesis()
print("MAD genesis %.1fs twin points %d coverage %.2f questions %s" % (time.time()-t, m.twin_cloud["count"], m.twin.coverage()["covered"], [q["type"] for q in m.questions]))
s = next(x for x in m.eval_pool if x.label == 1); rm = m.inspect(s.image(), truth=1, defect_type=s.defect_type)
print("MAD record", rm.decision, "twin heat max", max(rm.twin_heat) if rm.twin_heat else None)
