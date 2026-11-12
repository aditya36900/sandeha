import time, httpx
c = httpx.Client(base_url="http://127.0.0.1:8000", timeout=300)
for _ in range(60):
    try:
        c.get("/api/chaos/presets"); break
    except Exception: time.sleep(1)
def wait_ready(sid):
    for _ in range(240):
        s = c.get(f"/api/sessions/{sid}").json()
        if s["stage"] in ("INTERVIEW", "LINE"): return s
        time.sleep(1)
    raise SystemExit("genesis timeout")
def wait_records(sid, n):
    for _ in range(300):
        if c.get(f"/api/sessions/{sid}").json()["records"] >= n: return
        time.sleep(1)
sid = c.post("/api/sessions", json={"source": "VisA", "name": "pcb4"}).json()["id"]
s = wait_ready(sid); print("genesis ok, questions:", [q["type"] for q in s["questions"]])
c.post(f"/api/sessions/{sid}/stream", json={"n": 40, "defectRate": 0.3, "delay": 0.0}); wait_records(sid, 40)
p = c.get(f"/api/sessions/{sid}/performance").json(); print("40 parts: ours", p["ours"], "naive", p["naive"], "alarm", c.get(f"/api/sessions/{sid}").json()["shiftAlarm"])
c.post(f"/api/sessions/{sid}/conditions", json={"preset": "camera_bumped"})
c.post(f"/api/sessions/{sid}/stream", json={"n": 20, "defectRate": 0.0, "delay": 0.0}); wait_records(sid, 60)
recs = c.get(f"/api/sessions/{sid}/records").json()
print("after camera bump: alarm", c.get(f"/api/sessions/{sid}").json()["shiftAlarm"], "last 6", [(r["decision"], r["doubt_reason"]) for r in recs[-6:]])
print(c.post(f"/api/sessions/{sid}/adapt", json={"n": 5}).json()["message"])
c.post(f"/api/sessions/{sid}/stream", json={"n": 10, "defectRate": 0.0, "delay": 0.0}); wait_records(sid, 70)
recs = c.get(f"/api/sessions/{sid}/records").json(); print("after adapting (good parts):", [r["decision"] for r in recs[-10:]])
c.post(f"/api/sessions/{sid}/stream", json={"n": 20, "defectRate": 0.5, "delay": 0.0}); wait_records(sid, 90)
recs = c.get(f"/api/sessions/{sid}/records").json()[-20:]
d = [r for r in recs if r["truth"] == 1]
print(f"after adapting, mixed parts: {len(d)} defects -> escaped {sum(r['decision']=='PASS' for r in d)}, caught/asked {sum(r['decision']!='PASS' for r in d)}; policy", c.get(f"/api/sessions/{sid}").json()["policy"]["tau_fail"])
t = c.get(f"/api/sessions/{sid}/trust").json(); print("trust rows:", [(r["targetEscape"], round(r["reviewRate"], 3), int(r["ppm"])) for r in t["rows"]][:5])
cert = c.post(f"/api/sessions/{sid}/certificate").json(); v = c.get("/verify/" + cert["claim"]["certificate"]).text
print("certificate", cert["claim"]["certificate"], "verify page ok:", "Signature valid" in v)
g = c.get("/api/galaxy").json(); print("galaxy points", len(g["points"]))
a = c.post(f"/api/sessions/{sid}/ask", json={"question": "Why did you doubt this part?", "lang": "en"}).json(); print("ask:", a["mode"], "|", a["answer"][:140])
print("results files:", list(c.get("/api/results").json().keys()))
