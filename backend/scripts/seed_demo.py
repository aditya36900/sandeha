"""Seed a demo: two electronics lines (VisA pcb3 and pcb4) with a production run each."""
import time, httpx
c = httpx.Client(base_url="http://127.0.0.1:8000", timeout=300)
for _ in range(120):  # wait for the server to come up
    try:
        c.get("/api/chaos/presets"); break
    except httpx.HTTPError:
        time.sleep(1)
def ready(sid):
    for _ in range(300):
        s = c.get(f"/api/sessions/{sid}").json()
        if s["stage"] in ("INTERVIEW", "LINE"): return s
        time.sleep(1)
def records(sid, n):
    for _ in range(400):
        if c.get(f"/api/sessions/{sid}").json()["records"] >= n: return
        time.sleep(1)
bird = c.post("/api/sessions", json={"source": "VisA", "name": "pcb3"}).json()["id"]; ready(bird)  # second electronics line
pcb = c.post("/api/sessions", json={"source": "VisA", "name": "pcb4"}).json()["id"]; ready(pcb)
c.post(f"/api/sessions/{pcb}/stream", json={"n": 50, "defectRate": 0.15, "delay": 0.0}); records(pcb, 50)
c.post(f"/api/sessions/{bird}/stream", json={"n": 12, "defectRate": 0.4, "delay": 0.0}); records(bird, 12)
print("seeded", bird, pcb)
