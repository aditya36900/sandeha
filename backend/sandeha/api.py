"""HTTP + WebSocket API for the Sandeha dashboard."""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import threading
import time
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

from . import api_station, certificate, copilot, data, galaxy, persist, report
from .station import STATION
import os as _os
from .engine import SESSIONS, Session
from .events import bus
from .shift import PRESETS
from .visual import MEDIA

ROLES = {"OPERATOR", "INSPECTOR", "QUALITY_MANAGER"}


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    bus.bind(asyncio.get_running_loop())

    def warm():  # UMAP compiles with numba on first use; do it before anyone opens the galaxy
        try:
            import umap

            umap.UMAP(n_components=3, n_neighbors=5).fit_transform(np.random.default_rng(0).normal(size=(40, 8)))
        except Exception:
            pass
    threading.Thread(target=warm, daemon=True).start()

    import os

    persist_on = os.environ.get("SANDEHA_PERSIST", "1") != "0"
    if persist_on:
        api_station.load_station()
    if persist_on:  # restore saved product lines in the background: the server answers immediately
        def restore():
            SESSIONS.update(persist.load_all())
            bus.publish("sessions.restored", {"count": len(SESSIONS)})
            for _s in list(SESSIONS.values()):  # electronics lines saved before the component map existed
                try:
                    _s.ensure_board()
                except Exception:
                    pass
            if os.environ.get("SANDEHA_WARM_AI", "1") != "0":  # load the local models now, not on the first click
                try:
                    from PIL import Image as _Im

                    from . import regions as _rg, vlm as _vlm

                    _rg.clip_names([_Im.new("RGB", (224, 224))])
                    # the VLM is NOT pre-loaded: it would hold 4.4 GB of a 6 GB GPU and slow every scan;
                    # it loads on first use and unloads after 2 idle minutes
                    bus.publish("ai.ready", {"message": "Local vision models loaded"})
                except Exception as e:
                    bus.publish("ai.ready", {"message": f"Local vision models not loaded: {e}"})
        threading.Thread(target=restore, daemon=True, name="restore").start()

    stop = threading.Event()

    def autosave():  # save sessions that changed, every 90 s
        seen: dict[str, tuple] = {}
        while persist_on and not stop.wait(90):
            for sid, sess in list(SESSIONS.items()):
                key = (sess.stage, len(sess.records), len(sess.timeline), len(sess.learned_defects))
                if seen.get(sid) != key:
                    persist.save(sess)
                    seen[sid] = key
            api_station.save_station()
    threading.Thread(target=autosave, daemon=True).start()
    yield
    stop.set()
    if persist_on:
        for sess in list(SESSIONS.values()):
            persist.save(sess)
        api_station.save_station()


app = FastAPI(title="Sandeha", version="2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(api_station.router)
app.mount("/media", StaticFiles(directory=str(MEDIA)), name="media")


def S(sid: str) -> Session:
    s = SESSIONS.get(sid)
    if not s:
        raise HTTPException(404, f"Unknown session {sid}")
    return s


def _bg(fn, *a):
    def run():
        try:
            fn(*a)
        except Exception as e:  # surfaced to the UI
            import traceback

            traceback.print_exc()
            bus.publish("error", {"message": str(e)})
    threading.Thread(target=run, daemon=True).start()


# ------------------------------------------------------------------ catalog / sessions
@app.get("/api/catalog")
def catalog():
    out = []
    for c in data.catalog():
        if not c["name"].lower().startswith("pcb"):  # this station inspects electronics only
            continue
        p = data.load(c["source"], c["name"])
        thumb = p.train_good[0].path
        out.append({**c, "good": len(p.train_good), "test": len(p.test),
                    "defects": sum(s.label for s in p.test),
                    "defectTypes": sorted({t.strip() for s in p.test if s.label for t in s.defect_type.split(",") if t.strip()}),
                    "thumb": f"/api/thumb/{c['source']}/{c['name']}"})
    return out


@app.get("/api/thumb/{source}/{name}")
def thumb(source: str, name: str):
    from fastapi.responses import Response

    p = data.load(source, name)
    im = p.train_good[0].image().resize((256, 256))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=85)
    return Response(buf.getvalue(), media_type="image/jpeg")


class CreateIn(BaseModel):
    source: str
    name: str
    refs: int = 30
    seed: int = 0
    plant: str = "Plant A"


@app.post("/api/sessions")
def create(body: CreateIn):
    try:
        s = Session(body.source, body.name, body.refs, body.seed, body.plant)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(422, str(e))
    SESSIONS[s.id] = s
    _bg(s.genesis)
    return {"id": s.id, "stage": s.stage}


@app.get("/api/sessions")
def sessions():
    return [s.summary() for s in SESSIONS.values()]


@app.get("/api/sessions/{sid}")
def session(sid: str):
    return S(sid).summary()


@app.get("/api/sessions/{sid}/state")
def session_state(sid: str):
    return S(sid).state()


@app.get("/api/sessions/{sid}/twin")
def twin(sid: str):
    s = S(sid)
    if not s.twin:
        raise HTTPException(404, "This product has no posed views (no 3D twin)")
    return {**s.twin_cloud, "coverage": s.twin.coverage()}


class AnswerIn(BaseModel):
    qid: str
    option: str


@app.post("/api/sessions/{sid}/answer")
def answer(sid: str, body: AnswerIn):
    return S(sid).answer(body.qid, body.option)


class ZonesIn(BaseModel):
    points: list[dict]


@app.post("/api/sessions/{sid}/zones")
def zones(sid: str, body: ZonesIn):
    return S(sid).paint_zones(body.points)


# ------------------------------------------------------------------ the line
class StreamIn(BaseModel):
    n: int = 20
    defectRate: float = 0.15
    delay: float = 0.15
    ghostRate: float = 0.08


@app.post("/api/sessions/{sid}/stream")
def stream(sid: str, body: StreamIn):
    s = S(sid)

    def run():
        rng = np.random.default_rng(int(time.time()))
        for _ in range(body.n):
            smp = s.next_sample(body.defectRate, rng)
            if smp is None:  # uploaded photos all inspected
                bus.publish("line.exhausted", {"session": sid, "message": "All uploaded test photos inspected"})
                break
            known = smp.label >= 0
            ghost = bool(known and s.product.source != "Upload" and rng.random() < body.ghostRate)
            s.inspect(smp.image(), truth=smp.label if known else None,
                      defect_type=smp.defect_type if known else None, ghost=ghost)
            time.sleep(body.delay)
        bus.publish("line.batch_done", {"session": sid, "performance": s.performance()})
    _bg(run)
    return {"accepted": body.n}


@app.post("/api/sessions/{sid}/records/{rid}/explain")
async def explain(sid: str, rid: str, vision: bool = True):
    """What is wrong with this part: grounded facts plus the local VLM's description of each defect close-up."""
    try:
        return await run_in_threadpool(copilot.explain_record, S(sid), rid, vision)
    except KeyError:
        raise HTTPException(404, f"Unknown part {rid}")


@app.get("/api/sessions/{sid}/board")
async def board(sid: str):
    """The component map: golden board, every component with its type, footprint, 3D box and failure history."""
    return await run_in_threadpool(S(sid).board_public)


class FaultLabIn(BaseModel):
    component: str
    kind: str


@app.post("/api/sessions/{sid}/faultlab")
async def fault_lab(sid: str, body: FaultLabIn):
    """Rehearsal: plant a known fault on one component of a held-out good board, then scan it for real."""
    try:
        rec = await run_in_threadpool(S(sid).fault_lab, body.component, body.kind)
    except (ValueError, StopIteration) as e:
        raise HTTPException(409, str(e) or "Unknown component")
    return rec.to_dict()


# ------------------------------------------------------------------ electronics line + approval desk
@app.get("/api/sessions/{sid}/line")
async def smt_line(sid: str):
    from . import smt

    return await run_in_threadpool(smt.line_overview, S(sid))


@app.get("/api/sessions/{sid}/spc/{comp}")
async def smt_spc(sid: str, comp: str):
    from . import smt

    try:
        return await run_in_threadpool(smt.spc, S(sid), comp)
    except KeyError:
        raise HTTPException(404, f"Unknown component {comp}")


@app.get("/api/sessions/{sid}/materials")
async def smt_materials(sid: str):
    from . import smt

    return await run_in_threadpool(smt.materials, S(sid))


@app.get("/api/sessions/{sid}/rework")
async def smt_rework(sid: str):
    from . import smt

    return await run_in_threadpool(smt.rework_list, S(sid))


class ReworkIn(BaseModel):
    outcome: str


@app.post("/api/sessions/{sid}/rework/{rid}")
def smt_rework_close(sid: str, rid: str, body: ReworkIn, x_role: str | None = Header(None)):
    from . import smt
    from .api_station import NAMES, require

    r = require(x_role, "INSPECTOR", "QUALITY_MANAGER", "ADMIN")
    try:
        out = smt.close_ticket(S(sid), rid, body.outcome, NAMES[r])
    except ValueError as e:
        raise HTTPException(422, str(e))
    STATION.log(NAMES[r], r, "rework.close", rid, {"outcome": body.outcome})
    return out


class IpcIn(BaseModel):
    klass: int


@app.post("/api/sessions/{sid}/ipc")
def smt_ipc(sid: str, body: IpcIn, x_role: str | None = Header(None)):
    from .api_station import NAMES, require

    r = require(x_role, "QUALITY_MANAGER", "ADMIN")
    if body.klass not in (1, 2, 3):
        raise HTTPException(422, "IPC class must be 1, 2 or 3")
    S(sid).ipc_class = body.klass
    STATION.log(NAMES[r], r, "ipc.class", sid, {"class": body.klass})
    return {"ipcClass": body.klass}


@app.get("/api/profile")
def profile():
    """Which hardware profile the station runs, and what it costs per board (measured on this machine)."""
    from .backbone import DEVICE, EDGE, EDGE_RES, EDGE_THREADS, PROFILE

    lat = sorted(r.latency_ms for s in SESSIONS.values() for r in s.records[-200:] if r.latency_ms)
    mem = {s.id: {"patches": int(len(s.mem.bank)), **getattr(s, "memory_info", {})} for s in SESSIONS.values() if hasattr(s, "mem") and s.mem.bank is not None}
    return {"profile": "edge" if EDGE else "full", "requested": PROFILE, "device": DEVICE,
            "backbone": f"DINOv2-S INT8 ONNX @ {EDGE_RES} px, {EDGE_THREADS} CPU threads" if EDGE else "DINOv2-S fp16 @ 448 px",
            "detectors": ["patch memory", "golden-board deviation"], "goldenGain": float(_os.environ.get("SANDEHA_GOLDEN_GAIN", "0.02")),
            "vlm": not EDGE, "clip": not EDGE, "latencyMsP50": lat[len(lat) // 2] if lat else None, "memory": mem,
            "coreset": float(_os.environ.get("SANDEHA_CORESET", "0")) or (0.1 if EDGE else 0.0)}


@app.get("/api/sessions/{sid}/pulse")
async def smt_pulse(sid: str, n: int = 80):
    from . import smt

    return await run_in_threadpool(smt.pulse, S(sid), n)


@app.get("/api/sessions/{sid}/xray")
async def smt_xray(sid: str):
    from . import smt

    return await run_in_threadpool(smt.xray, S(sid))


@app.get("/api/sessions/{sid}/chips/{rid}")
async def chip_check(sid: str, rid: str):
    from . import chips

    try:
        return await run_in_threadpool(chips.check, S(sid), rid)
    except KeyError:
        raise HTTPException(404, f"Unknown part {rid}")


@app.get("/api/sessions/{sid}/approval")
async def approval_queue(sid: str):
    from . import approval

    return await run_in_threadpool(approval.queue, S(sid))


@app.get("/api/sessions/{sid}/dossier/{rid}")
async def approval_dossier(sid: str, rid: str):
    from . import approval

    try:
        return await run_in_threadpool(approval.dossier, S(sid), rid)
    except KeyError:
        raise HTTPException(404, f"Unknown part {rid}")


@app.get("/api/sessions/{sid}/dossier/{rid}/vlm")
async def approval_vlm(sid: str, rid: str):
    from . import approval

    try:
        return await run_in_threadpool(approval.vlm_view, S(sid), rid)
    except KeyError:
        raise HTTPException(404, f"Unknown part {rid}")


class LotIn(BaseModel):
    n: int = 12


@app.post("/api/sessions/{sid}/lot")
async def new_lot(sid: str, body: LotIn):
    """A fresh tray of unlabelled parts from the line."""
    return {"lot": await run_in_threadpool(S(sid).make_lot, max(1, min(body.n, 24)))}


@app.get("/api/sessions/{sid}/lot")
async def get_lot(sid: str):
    return {"lot": await run_in_threadpool(S(sid).lot_public)}


class ScanIn(BaseModel):
    token: str


@app.post("/api/sessions/{sid}/scan")
async def scan(sid: str, body: ScanIn):
    """Scan one part from the lot, live: verdict, heatmap, named defect regions with 3D anchors, stage timings."""
    s = S(sid)
    try:
        rec = await run_in_threadpool(s.scan, body.token)
    except KeyError:
        raise HTTPException(404, "That part is no longer on the tray")
    return rec.to_dict()


@app.post("/api/sessions/{sid}/inspect")
async def inspect_upload(sid: str, file: UploadFile = File(...)):
    s = S(sid)
    img = Image.open(io.BytesIO(await file.read())).convert("RGB")
    rec = await run_in_threadpool(s.inspect, img)
    return rec.to_dict()


@app.post("/api/sessions/{sid}/inspect-batch")
async def inspect_batch(sid: str, files: list[UploadFile] = File(...)):
    """Inspect your own photos (e.g. parts the organisers captured). Results stream to the line."""
    s = S(sid)
    blobs = [await f.read() for f in files]

    def run():
        for b in blobs:
            try:
                s.inspect(Image.open(io.BytesIO(b)).convert("RGB"))
            except Exception as e:
                bus.publish("error", {"message": f"Could not inspect one photo: {e}"})
    _bg(run)
    return {"accepted": len(blobs)}


@app.get("/api/sessions/{sid}/records/{rid}/heat")
def record_heat(sid: str, rid: str):
    r = next((x for x in S(sid).records if x.id == rid), None)
    if r is None:
        raise HTTPException(404, "Unknown part")
    return {"heat": r.twin_heat}


@app.get("/api/sessions/{sid}/queue")
def queue(sid: str):
    return S(sid).review_queue()


@app.get("/api/sessions/{sid}/report", response_class=HTMLResponse)
def risk_report(sid: str, download: bool = False):
    s = S(sid)
    headers = {"Content-Disposition": f'attachment; filename="sandeha-report-{s.name}.html"'} if download else None
    return HTMLResponse(report.build_html(s), headers=headers)


@app.get("/api/sessions/{sid}/decisions.csv")
def decisions(sid: str):
    from fastapi.responses import Response

    s = S(sid)
    return Response(report.decisions_csv(s), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="sandeha-decisions-{s.name}.csv"'})


@app.delete("/api/sessions/{sid}")
def delete_session(sid: str, x_role: str | None = Header(None)):
    r = api_station.require(x_role, "QUALITY_MANAGER", "ADMIN")
    STATION.log(api_station.NAMES[r], r, "product.delete", sid)
    S(sid)
    SESSIONS.pop(sid, None)
    persist.forget(sid)
    return {"deleted": sid}


@app.post("/api/uploads")
async def upload(files: list[UploadFile] = File(...), kind: str = "good", uid: str | None = None,
                 name: str | None = None, defectLabel: str | None = None):
    """Bring your own product: good/ reference photos, optional defect/ examples, test/ photos to inspect."""
    import re
    import uuid as _uuid

    if kind not in ("good", "defect", "test"):
        raise HTTPException(422, "kind must be good, defect or test")
    uid = re.sub(r"[^A-Za-z0-9_-]", "", uid or "") or f"U{_uuid.uuid4().hex[:6]}"
    root = data.UPLOAD_ROOT / uid
    (root / kind).mkdir(parents=True, exist_ok=True)
    meta_p = root / "meta.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
    if name:
        meta["name"] = name[:60]
    if defectLabel:
        meta["defectLabel"] = defectLabel[:60]
    meta_p.write_text(json.dumps(meta))
    saved = 0
    for f in files:
        b = await f.read()
        try:
            Image.open(io.BytesIO(b)).verify()  # only real images are kept
        except Exception:
            continue
        ext = Path(f.filename or "x.jpg").suffix.lower()
        ext = ext if ext in data.IMG_EXT else ".jpg"
        n = len(list((root / kind).glob("*")))
        (root / kind / f"{n:04d}{ext}").write_bytes(b)
        saved += 1
    counts = {k: len(list((root / k).glob("*"))) if (root / k).exists() else 0 for k in ("good", "defect", "test")}
    return {"uid": uid, "saved": saved, "counts": counts, "name": meta.get("name", uid)}


@app.get("/api/sessions/{sid}/records")
def records(sid: str, limit: int = 200):
    return [r.to_dict() for r in S(sid).records[-limit:]]


class ReviewIn(BaseModel):
    verdict: str  # GOOD / DEFECT
    reviewer: str
    role: str = "INSPECTOR"


@app.post("/api/sessions/{sid}/records/{rid}/review")
def review(sid: str, rid: str, body: ReviewIn):
    if body.verdict not in ("GOOD", "DEFECT"):
        raise HTTPException(422, "verdict must be GOOD or DEFECT")
    if body.role not in ("INSPECTOR", "QUALITY_MANAGER", "ADMIN"):
        raise HTTPException(403, "Only inspectors, quality managers and admins can review parts")
    return S(sid).review(rid, body.verdict, body.reviewer, body.role)


# ------------------------------------------------------------------ chaos / shift
@app.get("/api/chaos/presets")
def presets():
    return {k: v.__dict__ for k, v in PRESETS.items()}


@app.post("/api/sessions/{sid}/conditions")
def conditions(sid: str, body: dict):
    if "preset" in body:
        body = PRESETS[body["preset"]].__dict__ if body["preset"] in PRESETS else {}
    return S(sid).set_conditions(body)


@app.post("/api/sessions/{sid}/preview")
def preview(sid: str, body: dict):
    """What the camera would see under the given conditions (Chaos Lab live preview)."""
    from .shift import Conditions, perturb
    from .visual import b64

    s = S(sid)
    if not getattr(s, "ref_images", None):
        raise HTTPException(409, "Still learning")
    c = Conditions(**{k: float(v) for k, v in body.items() if k in Conditions().__dict__})
    img = s.ref_images[0]
    return {"before": b64(img, 320), "after": b64(perturb(img, c, seed=1), 320)}


class AdaptIn(BaseModel):
    n: int = 5


@app.post("/api/sessions/{sid}/adapt")
def adapt(sid: str, body: AdaptIn, x_role: str | None = Header(None)):
    r = api_station.require(x_role, "INSPECTOR", "QUALITY_MANAGER", "ADMIN")
    STATION.log(api_station.NAMES[r], r, "adapt", sid, {"photos": body.n})
    return S(sid).adapt(body.n)


# ------------------------------------------------------------------ trust
@app.get("/api/sessions/{sid}/trust")
def trust(sid: str, prevalence: float = 0.03, partsPerShift: int = 4000, costPerEscape: float = 2500):
    return S(sid).trust_curve(prevalence, partsPerShift, cost_escape=costPerEscape)


class TargetIn(BaseModel):
    targetEscape: float
    budget: float = 0.10


@app.post("/api/sessions/{sid}/trust")
def set_target(sid: str, body: TargetIn, x_role: str | None = Header(None)):
    r = api_station.require(x_role, "QUALITY_MANAGER", "ADMIN")
    STATION.log(api_station.NAMES[r], r, "trust.contract", sid, body.model_dump())
    return S(sid).set_target(body.targetEscape, body.budget)


@app.post("/api/sessions/{sid}/blindspots")
def blindspots(sid: str, kind: str = "scratch"):
    return S(sid).blind_spots(kind=kind)


@app.get("/api/sessions/{sid}/performance")
def performance(sid: str):
    return S(sid).performance()


@app.post("/api/sessions/{sid}/certificate")
def issue_certificate(sid: str, request: Request):
    return certificate.issue(S(sid), str(request.base_url))


@app.get("/api/certificates/{cid}")
def get_certificate(cid: str):
    c = certificate.get(cid)
    if not c:
        raise HTTPException(404, "certificate not found")
    return c


@app.get("/verify/{cid}", response_class=HTMLResponse)
def verify_page(cid: str):
    return certificate.verify_html(cid)


# ------------------------------------------------------------------ forecast / hive / galaxy / copilot
@app.post("/api/sessions/{sid}/wear")
def wear(sid: str, n: int = 60):
    _bg(S(sid).wear_stream, n)
    return {"accepted": n}


class HiveIn(BaseModel):
    to: str


@app.post("/api/sessions/{sid}/hive/share")
def hive_share(sid: str, body: HiveIn):
    src, dst = S(sid), S(body.to)
    fps = src.share_fingerprints()
    if not fps:
        raise HTTPException(409, "This plant has not learned any confirmed defect yet")
    n = dst.receive_fingerprints(fps)
    return {"shared": n, "labels": [f["label"] for f in fps], "bytesPerFingerprint": 384 * 4,
            "pixelsShared": 0}


@app.get("/api/galaxy")
def galaxy_api():
    return galaxy.build(list(SESSIONS.values()))


class AskIn(BaseModel):
    question: str
    recordId: str | None = None
    lang: str = "en"


@app.post("/api/sessions/{sid}/ask")
def ask(sid: str, body: AskIn):
    return copilot.answer(S(sid), body.question, body.recordId, body.lang)


@app.get("/api/edge")
def edge():
    p = Path(__file__).resolve().parents[2] / "data" / "results" / "edge.json"
    return json.loads(p.read_text()) if p.exists() else {"measured": False}


@app.middleware("http")
async def _no_cache_html(request, call_next):
    """Hashed JS/CSS may cache forever; index.html and API responses must not, or a new build never reaches the browser."""
    resp = await call_next(request)
    ct = resp.headers.get("content-type", "")
    if "text/html" in ct or request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.get("/api/version")
def version():
    import subprocess

    root = Path(__file__).resolve().parents[2]
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True, timeout=3).stdout.strip()
    except Exception:
        sha = ""
    idx = root / "frontend" / "dist" / "index.html"
    built = time.strftime("%Y-%m-%d %H:%M", time.localtime(idx.stat().st_mtime)) if idx.exists() else None
    return {"commit": sha or "unknown", "uiBuilt": built}


@app.post("/api/vlm/warm")
def vlm_warm():
    """Load the local vision-language model in the background so the first 'Ask it' does not wait 30 s."""
    from . import vlm

    if not vlm.available():
        return {"status": "unavailable"}
    if vlm._M is not None:
        return {"status": "ready", "model": vlm.MODEL}

    def run():
        try:
            from PIL import Image as _Im

            vlm.generate([_Im.new("RGB", (224, 224))], "Hi", 1)
        except Exception as e:
            print(f"[vlm] warm failed: {e}")
    threading.Thread(target=run, daemon=True).start()
    return {"status": "loading", "model": vlm.MODEL}


@app.get("/api/sessions/{sid}/sentinel")
async def sentinel_get(sid: str):
    from . import sentinel

    return await run_in_threadpool(sentinel.report, S(sid))


@app.post("/api/sessions/{sid}/sentinel/run")
async def sentinel_run(sid: str, n: int = 6):
    """Run a burst of planted-fault audits now (the station also does one by itself every few real boards)."""
    from . import sentinel

    s = S(sid)
    out = await run_in_threadpool(lambda: [sentinel.audit(s) for _ in range(max(1, min(n, 24)))])
    persist.save_async(s)  # the audit history survives a restart
    return {"ran": len([x for x in out if x]), "report": sentinel.report(s)}


@app.post("/api/sessions/{sid}/guard/reset")
def guard_reset(sid: str, x_role: str | None = Header(None)):
    """A supervisor checked the camera and lighting and found nothing wrong: clear the drift alarm (logged)."""
    from .api_station import NAMES, require

    r = require(x_role, "QUALITY_MANAGER", "ADMIN")
    s = S(sid)
    with s.lock:
        was = bool(s.guard.alarmed)
        s.guard.reset(s.global_calib, s.loo)
        s._alarm_announced = False
    STATION.resolve_category("SHIFT", s.id)
    STATION.log(NAMES[r], r, "guard.reset", sid, {"wasAlarmed": was})
    persist.save_async(s)
    return {"cleared": was}


@app.post("/api/sessions/{sid}/sentinel/reset")
def sentinel_reset(sid: str, x_role: str | None = Header(None)):
    from .api_station import NAMES, require

    r = require(x_role, "QUALITY_MANAGER", "ADMIN")
    s = S(sid)
    n = len(getattr(s, "audits", []))
    s.audits = []
    persist.save_async(s)
    STATION.log(NAMES[r], r, "sentinel.reset", sid, {"cleared": n})
    return {"cleared": n}


@app.get("/api/fewshot")
def fewshot():
    """Measured accuracy against the number of good photos learned from (scripts/fewshot_curve.py)."""
    f = Path(__file__).resolve().parents[2] / "data" / "results" / "fewshot.json"
    if not f.exists():
        raise HTTPException(404, "Not measured yet: run python backend/scripts/fewshot_curve.py")
    return json.loads(f.read_text())


@app.get("/api/fewshot/img/{name}")
def fewshot_img(name: str):
    import re

    from fastapi.responses import FileResponse

    if not re.fullmatch(r"[A-Za-z0-9_]+\.jpg", name):
        raise HTTPException(404, "No such picture")
    f = Path(__file__).resolve().parents[2] / "data" / "results" / "fewshot" / name
    if not f.exists():
        raise HTTPException(404, "No such picture")
    return FileResponse(f, media_type="image/jpeg")


@app.get("/api/results")
def results():
    root = Path(__file__).resolve().parents[2] / "data" / "results"
    out = {}
    for f in sorted(root.glob("p1_*.json")):
        rows = json.loads(f.read_text())
        out[f.stem] = rows
    return out


# ------------------------------------------------------------------ websocket
@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    q = bus.subscribe()
    try:
        await websocket.send_json({"type": "hello", "payload": {}})
        while True:
            await websocket.send_text(await q.get())
    except Exception:
        pass
    finally:
        bus.unsubscribe(q)


_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="ui")
