"""Product sessions: one live inspection brain per product line.

A session goes through GENESIS (references -> 3D twin -> features -> calibration -> imagination
-> curiosity interview -> galaxy) and then serves the production line: inspections, reviews
behind the feedback firewall, chaos/shift handling, adaptation, trust contracts, forecasts.
"""
from __future__ import annotations

import itertools
import math
import threading
import time
import uuid
from dataclasses import dataclass, field

import numpy as np
import torch
from PIL import Image

from . import data, regions as regionlib
from .backbone import Backbone
from .curiosity import interview
from .events import bus
from .imagine import DEFECT_TYPES, imagine, object_mask
from .memory import PatchMemory, deviation_signature, loo_scores
from .shift import Conditions, ShiftGuard, global_nonconformity, perturb
from .station import STATION
from .trust import Calibrator, conformal_upper, lower_quantile, outcome_stats, p_value, risk_coverage, wilson_upper
from .twin import Twin, load_view
from .visual import b64, brightness, crop_pct, overlay, save, sharpness

RES = 448
import os as _os

GOLDEN_GAIN = float(_os.environ.get("SANDEHA_GOLDEN_GAIN", "0.02"))  # distance units per spread beyond normal (measured)
CORESET = float(_os.environ.get("SANDEHA_CORESET", "0"))  # 0 = full memory; 0.1 = keep 10% (edge profile default)
_ids = itertools.count(1)


def _median_typicality(dist: torch.Tensor, fg: torch.Tensor) -> np.ndarray:
    """Median foreground patch distance per image: moves when the WHOLE surface changes
    (lighting, camera, finish) but barely moves for a local defect."""
    return np.array([float(d[m].median()) if m.any() else float(d.median()) for d, m in zip(dist, fg)])


ROUTING = {"PASS": "PASS_THROUGH", "FAIL": "EJECT", "DOUBT": "DIVERT_TO_REVIEW", "HOLD": "HOLD_ON_BELT"}


def _clf_report() -> dict | None:
    try:
        import json as _json

        from .board import CLF_FILE

        return _json.loads(CLF_FILE.with_suffix(".json").read_text())
    except Exception:
        return None


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class Record:
    id: str
    session: str
    index: int
    decision: str  # PASS / FAIL / DOUBT
    doubt_reason: str | None
    score: float
    uncertainty: float
    naive_decision: str
    truth: int | None
    defect_type: str | None
    image_url: str
    heat_url: str
    hotspot: dict
    precedents: list
    counterfactual: dict | None
    explanation: str
    conditions: dict
    martingale: float
    p_value: float
    novelty_p: float
    created: str
    review: dict = field(default_factory=dict)
    ghost: bool = False
    twin_heat: list | None = None
    pass_line: float | None = None
    hold_reason: str | None = None
    quality: dict | None = None
    latency_ms: float | None = None
    stage_ms: dict | None = None
    routing: str | None = None
    hive_match: dict | None = None
    regions: list | None = None  # named, measured defect regions with 3D anchors
    board: dict | None = None  # electronics: per-component verdicts (only the non-OK ones travel)
    synthetic: str | None = None  # fault-lab parts: what was planted, so they never pollute real metrics
    signals: dict | None = None  # the two detectors: patch-memory score, golden-board deviation, fused score
    foreign: str | None = None  # NOT_A_BOARD / NOT_THIS_BOARD: the photo is not what this line learned
    diff_url: str | None = None  # golden-board deviation painted over this board (blink comparator)

    def to_dict(self, heat: bool = False) -> dict:
        """Records travel light: the 3D heat (tens of thousands of numbers) is fetched only when viewed."""
        d = dict(self.__dict__)
        d["has_twin_heat"] = self.twin_heat is not None
        if not heat:
            d["twin_heat"] = None
        return d


_BOARD_BUILDS = threading.Semaphore(1)


class Session:
    def __init__(self, source: str, name: str, n_refs: int = 30, seed: int = 0, plant: str = "Plant A"):
        self.id = f"S{next(_ids)}-{uuid.uuid4().hex[:4]}"
        self.source, self.name, self.plant = source, name, plant
        self.product = data.load(source, name)
        self.n_refs, self.seed = n_refs, seed
        self.bb = None  # loaded in genesis (background), so creating a session is instant
        self.lock = threading.RLock()
        self.stage = "CREATED"
        self.created = _now()
        self.conditions = Conditions()
        self.records: list[Record] = []
        self.twin: Twin | None = None
        self.zone_weights: np.ndarray | None = None
        self.questions: list[dict] = []
        self.answers: dict = {}
        self.hive_library: list[dict] = []  # defect fingerprints received from other plants
        self.learned_defects: list[dict] = []  # defect fingerprints learned here
        self.pending_learning: list[dict] = []  # firewall queue
        self.reviewers: dict[str, dict] = {}
        self.stream_pos = 0
        self.forecast: dict = {}
        self.timeline: list[dict] = []
        self.galaxy_points: list[dict] = []
        good, known, ev = self.product.few_shot(n_refs, 5, seed)
        self.ref_samples, self.known_defects, self.eval_pool = good, known, ev
        used = {id(s) for s in good}
        self.spare_good = [s for s in self.product.train_good if id(s) not in used]
        self.aligned = self.product.source in ("VisA", "Upload")  # fixed camera
        self.relief = False
        self._upload_cursor = 0
        if len(good) < 8:
            raise ValueError(f"Need at least 8 good reference photos; got {len(good)}. 20-30 is better.")

    # ================================================================== events
    def emit(self, kind: str, **payload) -> None:
        payload = {"session": self.id, **payload}
        if payload.get("message"):
            self.timeline.append({"t": time.time(), "kind": kind, "text": payload["message"]})
            del self.timeline[:-80]
        bus.publish(kind, payload)

    def state(self) -> dict:
        """Everything the dashboard needs to rebuild this session after a page refresh."""
        tone = {"genesis.imagination": "doubt", "genesis.interview": "doubt", "shift.alarm": "doubt",
                "genesis.ready": "pass", "shift.adapted": "pass"}
        return {
            "summary": self.summary(),
            "photos": getattr(self, "thumbs", []),
            "imagined": getattr(self, "gallery", []),
            "cloud": self.cloud(),
            "records": [r.to_dict() for r in self.records[-400:]],
            "narration": [{"t": e["t"] * 1000, "text": e["text"], "tone": tone.get(e["kind"], "plain")} for e in self.timeline],
            "patches": int(len(self.mem.bank)) if hasattr(self, "mem") else None,
        }

    # ================================================================== GENESIS
    def genesis(self) -> None:
        with self.lock:
            self.stage = "GENESIS"
            self.bb = Backbone.get("facebook/dinov2-small", RES)
            refs = [s.image() for s in self.ref_samples]
            self.ref_images = refs
            self.thumbs = [b64(im, 96) for im in refs]
            self.emit("genesis.photos", message=f"{len(refs)} reference photos received", thumbs=self.thumbs)

            if self.product.source == "MAD-Sim":
                self._carve_twin()
            else:
                self._relief_twin(refs[0])

            t = time.time()
            self.mem = PatchMemory(self.bb).fit(refs)
            self._compact_memory()
            self.gref = self.bb(refs)
            self.emit("genesis.features", message=f"Learned {len(self.mem.bank):,} visual patch memories in "
                                                   f"{time.time() - t:.1f}s (no training)", patches=len(self.mem.bank))

            g, dist, sc = self.mem.inspect(refs, exclude_src=list(range(len(refs))))
            self.loo = sc.cpu().numpy()
            self.loo_median = _median_typicality(dist, g.fg)
            self.loo_maps = self.mem.anomaly_maps(dist, g.fg, 256)
            self.global_calib = global_nonconformity(self.gref.cls, self.gref.cls, exclude_self=True).cpu().numpy()

            self.emit("genesis.imagination", message="Imagining defects I have never seen...")
            self._imagine()
            self._calibrate()
            self.guard = ShiftGuard(self.global_calib, self.loo)
            self.emit("genesis.calibration", message="Calibrated my doubt", policy=self.cal.policy.to_dict())

            cov = self.twin.coverage() if self.twin else None
            pool_dirs = None
            if self.twin:
                pool_dirs = np.stack([s.pose[:3, 3] / np.linalg.norm(s.pose[:3, 3]) for s in self.spare_good])
            iv = interview(self.loo, self.loo_maps, refs, aligned=self.aligned, coverage=cov, pool_dirs=pool_dirs)
            self.questions = iv["questions"]
            self.sufficiency = iv["sufficiency"]
            self.emit("genesis.interview", message=f"I have {len(self.questions)} questions before I start",
                      questions=self.questions)
            self._probe_baseline()
            self.stage = "INTERVIEW"
            self.emit("genesis.ready", message="Ready for the line", summary=self.summary())
        self.ensure_board()

    def _carve_twin(self) -> None:
        self.twin = Twin(128, 1.0)
        views = [load_view(s.path, s.pose, self.product.fov_x) for s in self.ref_samples]
        for k, v in enumerate(views):
            occ = self.twin.carve(v)
            if k in (0, 1, 2, 4, 7, 11, 16, 22, len(views) - 1):
                ex = self.twin.export(max_points=9000 if k < len(views) - 1 else 40000)
                self.emit("genesis.carve", step=k + 1, total=len(views), occupied=occ,
                          message=f"Carving 3D twin: view {k + 1}/{len(views)}", cloud=ex)
        self.twin_cloud = self.twin.export(max_points=40000)

    def cloud(self) -> dict | None:
        """The 3D twin for the dashboard. A single-photo relief also carries which points are the part itself
        (silhouette from part_mask), so the table/background under the part is not drawn as a wall."""
        c = getattr(self, "twin_cloud", None)
        if c and c.get("relief") and "fg" not in c and getattr(self, "ref_images", None):
            import cv2

            try:
                fgs = self.gref.fg.reshape(-1, *self.gref.hw).cpu().numpy()
                m = self.part_mask(self.ref_images[0], fgs[0])
                m = cv2.dilate(m.astype(np.uint8), np.ones((15, 15), np.uint8))
                n = int(c["grid"])
                g = cv2.resize(m, (n, n), interpolation=cv2.INTER_NEAREST)
                if 0.05 < g.mean() < 0.98:
                    c["fg"] = g.reshape(-1).astype(int).tolist()
            except Exception:
                pass
        return c

    def _relief_twin(self, img: Image.Image) -> None:
        """Single camera: no poses to carve from, so lift one photo into a 3D relief (monocular depth)."""
        try:
            from . import depth

            self.emit("genesis.carve", step=0, total=1, occupied=0, cloud=None,
                      message="Estimating the part's 3D surface from one photo...")
            d = depth.estimate(img)
            self.twin_cloud = depth.relief_cloud(img, d)
            self.relief = True
            self.emit("genesis.carve", step=1, total=1, occupied=self.twin_cloud["count"], cloud=self.twin_cloud,
                      message=f"Lifted a {self.twin_cloud['count']:,}-point 3D relief from a single photo")
        except Exception as e:  # depth model unavailable offline: the rest of the pipeline does not need it
            self.emit("genesis.carve", step=0, total=1, occupied=0, cloud=None,
                      message=f"3D relief skipped ({type(e).__name__}); inspection is unaffected")

    def _known_scores(self, weighted: bool = False) -> np.ndarray:
        if not self.known_defects:
            return np.zeros(0)
        ims = [s.image() for s in self.known_defects]
        g, d, sc = self.mem.inspect(ims)
        d = self._fused(d, ims)
        return (self._weighted_score(d, self._board_fg(ims, g)) if weighted else self.mem.score(d, g.fg)).cpu().numpy()

    def _imagine(self) -> None:
        rng = np.random.default_rng(self.seed)
        fg = [f.reshape(self.gref.hw).cpu().numpy() for f in self.gref.fg]
        imagined = []
        for i in range(70):
            j = i % len(self.ref_images)
            kind = DEFECT_TYPES[i % len(DEFECT_TYPES)]
            size = float(rng.uniform(0.03, 0.11)) * self.ref_images[j].width
            m = object_mask(self.ref_images[j], fg[j])
            imagined.append(imagine(self.ref_images[j], kind, size, rng, mask=m,
                                    donor=self.ref_images[(j + 1) % len(self.ref_images)]))
        scores = []
        for i in range(0, len(imagined), 16):
            _, _, s = self.mem.inspect([x.image for x in imagined[i:i + 16]])
            scores += s.tolist()
        self.imagined = imagined
        self.imagined_scores = np.array(scores)
        self.known_scores = self._known_scores()
        gallery = []
        for x, s in list(zip(imagined, scores))[:14]:
            gallery.append({"kind": x.kind, "sizePct": round(100 * x.size_px / x.image.width, 1),
                            "score": round(float(s), 4), "thumb": b64(x.image, 128)})
        self.gallery = gallery
        self.emit("genesis.imagined", message=f"Imagined {len(imagined)} defects of {len(DEFECT_TYPES)} kinds",
                  gallery=gallery)

    def _calibrate(self, budget: float | None = None, target_escape: float | None = None) -> None:
        defects = np.concatenate([self.known_scores, self.imagined_scores])
        self.cal = Calibrator(self.loo, defects, alpha_fr=0.02, beta=target_escape or 0.05,
                              budget=budget if budget is not None else getattr(self, "budget", 0.10))
        self.tau_naive = conformal_upper(self.loo, 0.05)

    # ================================================================== interview answers
    def answer(self, qid: str, option: str) -> dict:
        with self.lock:
            q = next((q for q in self.questions if q["id"] == qid), None)
            if q is None:
                raise KeyError(qid)
            self.answers[qid] = option
            effect = "noted"
            if q["type"] == "SUSPECT_REFERENCE" and "remove" in option.lower():
                i = q["refIndex"]
                keep = [k for k in range(len(self.ref_images)) if k != i]
                self.ref_samples = [self.ref_samples[k] for k in keep]
                self._rebuild_refs([self.ref_images[k] for k in keep])
                effect = f"Removed photo #{i + 1} from my memory and re-calibrated"
            elif q["type"] == "VARIATION_ZONE":
                self._zone_weight(q["x"] / 100, q["y"] / 100, 0.8 if "accept" in option.lower() else 1.25)
                effect = "Relaxed that zone" if "accept" in option.lower() else "I'll be stricter in that zone"
            elif q["type"] == "COVERAGE_GAP" and "add" in option.lower() and self.twin is not None:
                k = q.get("suggestedView")
                if k is not None:
                    s = self.spare_good[k]
                    self.ref_samples.append(s)
                    self.twin.carve(load_view(s.path, s.pose, self.product.fov_x))
                    self.twin_cloud = self.twin.export(max_points=40000)
                    self._rebuild_refs(self.ref_images + [s.image()])
                    effect = "Added the missing viewpoint to the twin and memory"
                    self.emit("genesis.carve", step=len(self.twin.views), total=len(self.twin.views),
                              occupied=int(self.twin.occ.sum()), message="Twin updated", cloud=self.twin_cloud)
            elif q["type"] == "SUFFICIENCY" and "add" in option.lower():
                extra = self.spare_good[:10]
                self.spare_good = self.spare_good[10:]
                self.ref_samples += extra
                self._rebuild_refs(self.ref_images + [s.image() for s in extra])
                effect = "Added 10 more reference photos and re-calibrated"
            q["answered"] = option
            q["effect"] = effect
            if all("answered" in x for x in self.questions):
                self.stage = "LINE"
            self.emit("interview.answer", qid=qid, effect=effect, policy=self.cal.policy.to_dict(), message=effect)
            return {"effect": effect, "policy": self.cal.policy.to_dict(), "stage": self.stage}

    def _zone_weight(self, x: float, y: float, w: float) -> None:
        h = self.mem.hw[0]
        if self.zone_weights is None:
            self.zone_weights = np.ones((h, h), np.float32)
        yy, xx = np.mgrid[0:h, 0:h] / h
        g = np.exp(-(((xx - x) ** 2 + (yy - y) ** 2) / (2 * 0.08 ** 2)))
        self.zone_weights *= (1 + (w - 1) * g).astype(np.float32)
        self._recalibrate_zones()

    def paint_zones(self, points: list[dict]) -> dict:
        """Critical zones painted by the human: [{x, y, r, strictness}] in [0,1] image coordinates."""
        with self.lock:
            h = self.mem.hw[0]
            self.zone_weights = np.ones((h, h), np.float32)
            yy, xx = np.mgrid[0:h, 0:h] / h
            for p in points:
                g = np.exp(-(((xx - p["x"]) ** 2 + (yy - p["y"]) ** 2) / (2 * max(p.get("r", 0.08), 0.02) ** 2)))
                self.zone_weights *= (1 + (float(p.get("strictness", 1.5)) - 1) * g).astype(np.float32)
            self._recalibrate_zones()
            return {"policy": self.cal.policy.to_dict()}

    # ---------------------------------------------------------- electronics: only the board counts
    def _board_patch_mask(self, img: Image.Image) -> np.ndarray | None:
        """The board's outline (from the component map) carried onto this photo, on the backbone's patch grid."""
        import cv2

        from .board import align, to_work

        bm = getattr(self, "board", None)
        if bm is None:
            return None
        work = to_work(img)
        _, warp = align(work, bm.golden)
        H, W = work.shape[:2]
        m = cv2.warpAffine(bm.board.astype(np.uint8) * 255, warp, (W, H), flags=cv2.INTER_NEAREST)  # golden -> photo
        m = cv2.dilate(m, np.ones((9, 9), np.uint8))
        h, w = self.mem.hw
        return (cv2.resize(m.astype(np.float32) / 255, (w, h), interpolation=cv2.INTER_AREA) > 0.3).reshape(-1)

    def _board_fg(self, images: list[Image.Image], g) -> torch.Tensor:
        """Backbone foreground AND the board: the mat, table or fixture around a PCB never scores."""
        if getattr(self, "board", None) is None or not getattr(self, "_board_calibrated", False) and not getattr(self, "_calibrating_board", False):
            return g.fg
        masks = [self._board_patch_mask(im) for im in images]
        if any(m is None for m in masks):
            return g.fg
        m = torch.from_numpy(np.stack(masks)).to(g.fg.device)
        out = g.fg & m
        keep = out.sum(1) > 0.2 * g.fg.sum(1)  # alignment failed on a photo: fall back to the plain foreground
        return torch.where(keep[:, None], out, g.fg)

    def _board_recalibrate(self) -> None:
        """Re-score references (leave-one-out), real and imagined defects on board pixels only, then rebuild the lines."""
        self._calibrating_board = True
        try:
            self._recalibrate_zones()
            # Board-only references scored leave-one-out look more alike than new boards do, which would put the fail
            # line too low (measured: 6.2% false rejects on held-out good boards vs a 2% guarantee). Calibrate the good-
            # board side on separate good boards that were never references: those are exchangeable with future boards.
            spare = [x for x in self.spare_good if x.label == 0][:40] if self.product.source != "Upload" else []
            if len(spare) >= 30:
                sc = []
                for i in range(0, len(spare), 8):
                    ims = [x.image() for x in spare[i:i + 8]]
                    g, d, _ = self.mem.inspect(ims)
                    d = self._fused(d, ims)
                    sc += self._weighted_score(d, self._board_fg(ims, g)).tolist()
                self.loo = np.array(sc)
                self.calibrated_on = f"{len(spare)} separate good boards (board pixels only)"
                self._calibrate()
                self.guard.reset(calib_local=self.loo)
            else:
                self.calibrated_on = f"{len(self.ref_images)} references, leave-one-out (board pixels only)"
            self._board_calibrated = True
        finally:
            self._calibrating_board = False

    def _compact_memory(self) -> None:
        from .backbone import EDGE

        frac = CORESET or (0.1 if EDGE else 0.0)
        if frac and self.mem.bank is not None:
            info = self.mem.coreset(frac)
            self.memory_info = {"coreset": frac, **info}

    def _fused(self, dist: torch.Tensor, images: list[Image.Image], loo: list[int] | None = None) -> torch.Tensor:
        """Add the golden-board deviation (second detector) to the patch distances, so score, heatmap, regions,
        components and calibration all see one map. loo[i] = reference index to leave out of the statistics."""
        gs = getattr(self, "golden", None)
        if gs is None or GOLDEN_GAIN <= 0:
            return dist
        from .golden import fuse

        out = dist.clone()
        for i, im in enumerate(images):
            try:
                z = gs.patch_map(im, self.mem.hw, exclude=None if loo is None else loo[i])
            except Exception:
                continue
            out[i:i + 1] = fuse(out[i:i + 1], z, GOLDEN_GAIN)
        return out

    def _weighted_score(self, dist: torch.Tensor, fg: torch.Tensor) -> torch.Tensor:
        if self.zone_weights is None:
            return self.mem.score(dist, fg)
        w = torch.from_numpy(self.zone_weights.reshape(-1)).to(dist.device)
        return self.mem.score(dist * w, fg)

    def _recalibrate_zones(self) -> None:
        g, dist, _ = self.mem.inspect(self.ref_images, exclude_src=list(range(len(self.ref_images))))
        dist = self._fused(dist, self.ref_images, loo=list(range(len(self.ref_images))))
        self.loo = self._weighted_score(dist, self._board_fg(self.ref_images, g)).cpu().numpy()
        sc = []
        for i in range(0, len(self.imagined), 16):
            batch = [x.image for x in self.imagined[i:i + 16]]
            gi, di, _ = self.mem.inspect(batch)
            di = self._fused(di, batch)
            sc += self._weighted_score(di, self._board_fg(batch, gi)).tolist()
        self.imagined_scores = np.array(sc)
        self.known_scores = self._known_scores(weighted=True)
        self._calibrate()
        self.guard.reset(calib_local=self.loo)

    def _rebuild_refs(self, refs: list[Image.Image]) -> None:
        self.ref_images = refs
        self.mem = PatchMemory(self.bb).fit(refs)
        self._compact_memory()
        self.gref = self.bb(refs)
        g, dist, _ = self.mem.inspect(refs, exclude_src=list(range(len(refs))))
        self.loo = self._weighted_score(dist, g.fg).cpu().numpy()
        self.loo_median = _median_typicality(dist, g.fg)
        self.loo_maps = self.mem.anomaly_maps(dist, g.fg, 256)
        self.global_calib = global_nonconformity(self.gref.cls, self.gref.cls, exclude_self=True).cpu().numpy()
        self._recalibrate_zones()
        self.guard.reset(self.global_calib, self.loo)

    # ================================================================== INSPECTION
    def next_sample(self, defect_rate: float = 0.15, rng=None) -> data.Sample | None:
        if self.product.source == "Upload":  # walk through the uploaded test photos in order
            pool = self.eval_pool or self.spare_good
            if self._upload_cursor >= len(pool):
                return None
            self._upload_cursor += 1
            self.stream_pos += 1
            return pool[self._upload_cursor - 1]
        rng = rng or np.random.default_rng(self.stream_pos + 1000 * self.seed)
        goods = [s for s in self.eval_pool if s.label == 0] + self.spare_good[-60:]
        defects = [s for s in self.eval_pool if s.label == 1]
        pool = defects if (rng.random() < defect_rate and defects) else goods
        s = pool[int(rng.integers(len(pool)))]
        self.stream_pos += 1
        return s

    # ================================================================== PRODUCTION LOT (unlabelled parts)
    def make_lot(self, n: int = 12) -> list[dict]:
        """A tray of parts straight off the line. Nobody - not the operator, not the UI - knows which are
        defective: the mix is drawn at random and the truth stays on the server until a part is scanned."""
        with self.lock:
            rng = np.random.default_rng()
            rate = float(rng.uniform(0.1, 0.4))
            lot = {}
            for _ in range(n):
                smp = self.next_sample(rate, rng)
                if smp is None:
                    break
                tok = uuid.uuid4().hex[:10]
                lot[tok] = (smp, save(smp.image().resize((160, 160)), f"{self.id}/lot/{tok}.jpg", 80))
            self.lot = lot
            return self.lot_public()

    def lot_public(self) -> list[dict]:
        lot = getattr(self, "lot", None) or {}
        return [{"token": tok, "thumb": v[1]} for tok, v in lot.items() if isinstance(v, tuple)]

    def scan(self, token: str) -> Record:
        lot = getattr(self, "lot", None) or {}
        v = lot.pop(token, None)
        if not isinstance(v, tuple):
            raise KeyError(token)
        smp = v[0]
        known = smp.label >= 0
        rec = self.inspect(smp.image(), truth=smp.label if known else None, defect_type=smp.defect_type if known else None)
        self._sentinel_maybe()
        return rec

    def inspect(self, image: Image.Image, truth: int | None = None, defect_type: str | None = None,
                ghost: bool = False) -> Record:
        with self.lock:
            idx = len(self.records)
            rid = f"{self.id}-P{idx + 1:04d}"
            t0 = time.perf_counter()
            st = STATION
            if "camera" in st.faults:  # dead sensor: black frames
                image = Image.new("RGB", image.size, (6, 6, 8))
            if "accelerator" in st.faults:  # throttled inference
                time.sleep(0.6)
            shown = perturb(image, self.conditions, seed=idx) if not self.conditions.is_identity() else image.convert("RGB")
            t1 = time.perf_counter()
            g, dist, _ = self.mem.inspect([shown])
            fg_eff = self._board_fg([shown], g)  # electronics: only board pixels count
            patch_score = float(self._weighted_score(dist, fg_eff)[0])
            dist = self._fused(dist, [shown])
            t2 = time.perf_counter()
            score = float(self._weighted_score(dist, fg_eff)[0])
            signals = {"patchMemory": round(patch_score, 5), "goldenDeviation": round(score - patch_score, 5), "fused": round(score, 5),
                       "gain": GOLDEN_GAIN, "detectors": 2 if getattr(self, "golden", None) is not None and GOLDEN_GAIN > 0 else 1}
            nov = float(global_nonconformity(g.cls, self.gref.cls)[0])
            novelty_p = p_value(nov, self.global_calib)
            # Is this even the right thing in front of the camera? Measured on VisA (scripts/foreign_check.py):
            # this board's good and defective photos stay under ~0.06 (a few pcb1 defects with a whole part gone
            # reach 0.27), another PCB type is 0.07-0.44, anything that is not a circuit board (a person, a hand,
            # food, a blank or noisy frame) is 0.88 or more.
            unlike_line = max(0.06, 3 * float(np.max(self.global_calib))) if len(self.global_calib) else 0.06
            foreign = "NOT_A_BOARD" if nov > 0.6 else "NOT_THIS_BOARD" if (self.electronics and nov > unlike_line) else None
            if foreign:  # a photo of something else is not evidence that the lighting or camera changed
                h = dict(self.guard.history[-1]) if self.guard.history else {"p": 1.0, "martingale": 1.0, "alarm": self.guard.alarmed}
            else:
                h = self.guard.update(nov, score)
            pol = self.cal.policy
            pass_line = self._live_pass_line()
            decision, unc = self.cal.decide(score, pass_line)
            reason = None
            if not hasattr(self, "_ref_quality"):
                self._ref_quality = (max(float(np.median([sharpness(r) for r in self.ref_images[:8]])), 1e-6),
                                     max(float(np.mean([brightness(r) for r in self.ref_images[:8]])), 1e-6))
            sharp_ratio = sharpness(shown) / self._ref_quality[0]
            bright_ratio = brightness(shown) / self._ref_quality[1]
            glare = float((np.asarray(shown.convert("L").resize((256, 256))) > 250).mean())
            quality = {"sharpness": round(sharp_ratio, 3), "exposure": round(bright_ratio, 3), "glarePct": round(100 * glare, 2)}
            hold_reason = None
            if st.hold:
                hold_reason = f"Emergency HOLD ({st.hold_reason or 'manual stop'})"
            elif bright_ratio < 0.45:
                hold_reason = "Image too dark to judge (camera or lighting fault)"
            elif bright_ratio > 1.8 or glare > 0.25:
                hold_reason = "Image over-exposed or glare-washed"
            elif sharp_ratio < 0.35:
                hold_reason = "Image too blurred to judge (motion or focus)"
            elif "conveyor" in st.faults:
                hold_reason = "Conveyor tracking lost: the part cannot be routed safely"
            if foreign == "NOT_A_BOARD" and not hold_reason:  # a camera / lighting fault is the more useful message
                hold_reason = (f"This is not a {self.product.name} circuit board (it looks like nothing I learned: similarity "
                               f"{1 - nov:.2f}, a real board scores above 0.94). Put a board in front of the camera")
            if hold_reason:
                decision, reason, unc = "HOLD", None, 1.0
            elif foreign == "NOT_THIS_BOARD":
                # Either another board type (this line's part map does not apply to it) or a defect so large the
                # whole board looks different. Never auto-pass, never name parts from the wrong map: a person checks.
                decision, reason, unc = "DOUBT", "NOT_THIS_BOARD", max(unc, 0.9)
            elif self.guard.alarmed and (decision == "PASS" or (decision == "FAIL" and score < 1.5 * pol.tau_fail)):
                # under a detected shift neither direction is trustworthy: no auto-pass, no auto-reject
                decision, reason, unc = "DOUBT", "CONDITIONS_CHANGED", max(unc, 0.85)
            elif decision == "DOUBT":
                reason = "NEVER_SEEN" if novelty_p < 0.02 else "BORDERLINE"
            elif decision == "PASS" and novelty_p < 0.01:
                decision, reason, unc = "DOUBT", "NEVER_SEEN", 0.9

            naive = "FAIL" if score > self.tau_naive else "PASS"

            hm = self.mem.anomaly_maps(dist, fg_eff, 256)[0]
            if self.zone_weights is not None:
                zw = np.asarray(Image.fromarray(self.zone_weights).resize((256, 256), Image.BILINEAR))
                hm = hm * zw
            y, x = np.unravel_index(int(np.argmax(hm)), hm.shape)
            hot = {"x": round(x / 256, 4), "y": round(y / 256, 4), "value": round(float(hm.max()), 4)}
            img_url = save(shown.resize((384, 384)), f"{self.id}/{rid}.jpg")
            heat_url = save(overlay(shown, hm, pol.tau_pass * 0.8, pol.tau_fail * 1.6), f"{self.id}/{rid}_heat.jpg")

            prec, cf = self._case_law(g, dist, shown, hot)
            hive = self._hive_match(g, dist) if self.hive_library and decision != "HOLD" else None
            if hive and decision != "FAIL":
                decision, reason, unc = "FAIL", None, 0.2
            rec_hive = hive
            t3 = time.perf_counter()
            expl = self._explain(decision, reason, score, pol, novelty_p, h, hive, pass_line, hold_reason)
            rec = Record(id=rid, session=self.id, index=idx, decision=decision, doubt_reason=reason,
                         score=round(score, 5), uncertainty=round(float(unc), 3), naive_decision=naive, truth=truth,
                         defect_type=defect_type, image_url=img_url, heat_url=heat_url, hotspot=hot,
                         precedents=prec, counterfactual=cf, explanation=expl, conditions=self.conditions.__dict__.copy(),
                         martingale=h["martingale"], p_value=round(p_value(score, self.loo), 4),
                         novelty_p=round(novelty_p, 4), created=_now(), ghost=ghost, hive_match=rec_hive,
                         pass_line=round(pass_line, 5), hold_reason=hold_reason, quality=quality,
                         routing=ROUTING[decision])
            rec.signals = signals
            if getattr(self, "golden", None) is not None:
                try:
                    rec.diff_url = save(self.golden.diff_image(shown), f"{self.id}/{rid}_diff.jpg")
                except Exception:
                    pass
            if self.twin is not None:
                rec.twin_heat = self._project_to_twin(g, hm)
            elif self.relief:
                from .depth import sample_heat

                tp = self.cal.policy.tau_pass
                rec.twin_heat = [round(min(1.0, max(0.0, v / max(tp * 2, 1e-9))), 3)
                                 for v in sample_heat(hm, self.twin_cloud["grid"])]
            t35 = time.perf_counter()
            rec.foreign = foreign
            if foreign == "NOT_A_BOARD":  # no heat map, no 3D heat and no golden-board diff on a photo of something else
                rec.heat_url, rec.twin_heat, rec.diff_url = rec.image_url, None, None
            if decision in ("FAIL", "DOUBT") and not foreign:
                try:
                    rec.regions = self.analyse_regions(g, dist, hm, shown, rid)
                except Exception as e:  # never let naming break an inspection
                    rec.regions = []
                    self.emit("regions.error", message=f"Region analysis failed: {e}")
            bm = getattr(self, "board", None)
            if bm is not None and decision != "HOLD" and not foreign:
                try:
                    rec.board = self._board_check(bm, shown, hm, rec)
                except Exception as e:  # never let the component check break an inspection
                    self.emit("board.error", message=f"Component check failed: {e}")
            t4 = time.perf_counter()
            rec.stage_ms = {"see": round(1000 * (t1 - t0), 1), "understand+compare": round(1000 * (t2 - t1), 1),
                            "doubt+decide": round(1000 * (t3 - t2), 1), "explain": round(1000 * (t35 - t3), 1),
                            "regions": round(1000 * (t4 - t35), 1)}
            rec.latency_ms = round(1000 * (t4 - t0), 1)
            self.records.append(rec)
            st.send("zenoh", {"topic": f"sandeha/{self.plant}/{self.product.name}/decision",
                              "part": rid, "decision": decision, "routing": rec.routing})
            if decision == "DOUBT":
                st.send("telegram", {"text": f"Part {rid} ({self.product.name}) needs a person: {reason or 'unsure'}"})
            self._feat_cache = getattr(self, "_feat_cache", {})
            if foreign != "NOT_A_BOARD":  # a non-board photo is never learned from
                self._feat_cache[rid] = (g.feats[0][g.fg[0]].detach(), dist[0][g.fg[0]].detach(), g.cls[0].detach())
            self._trim_cache()
            self._update_forecast()
            self.emit("line.record", record=rec.to_dict())
            if h["alarm"] and not getattr(self, "_alarm_announced", False):
                self._alarm_announced = True
                self.emit("shift.alarm", message="Conditions changed - auto-pass suspended",
                          martingale=h["martingale"], at=rid)
                st.raise_alert(f"Line conditions changed ({self.product.name})",
                               "The line no longer looks like the references; automatic approval is suspended.",
                               "CRITICAL", "SHIFT", self.id, "Show 5 good parts under the new conditions (Chaos Lab)")
            self._check_overload()
            if self.forecast.get("status") == "STORM_COMING":
                st.raise_alert(f"Defect storm forecast ({self.product.name})",
                               f"Weak anomalies are rising; about {self.forecast.get('partsUntilStorm')} parts until they "
                               f"cross the pass line.", "WARNING", "FORECAST", self.id, "Check the tool or fixture")
            return rec

    def _check_overload(self) -> None:
        limit = int(STATION.settings.get("overloadQueue", 12))
        pending = sum(1 for r in self.records if r.decision == "DOUBT" and not r.ghost
                      and r.review.get("final") not in ("GOOD", "DEFECT", "GHOST_CHECKED"))
        if pending > limit:
            STATION.raise_alert(f"Review queue overloaded ({self.product.name})",
                                f"{pending} parts are waiting for a person (limit {limit}).", "WARNING", "OVERLOAD",
                                self.id, "Add a reviewer or tighten the trust contract")
        elif pending <= limit // 2:
            STATION.resolve_category("OVERLOAD", self.id)

    def _trim_cache(self, keep_recent: int = 40) -> None:
        """Patch features are ~1 MB per part: keep them only for parts a person may still review
        (or the most recent ones); everything else keeps just its 384-number global embedding."""
        recent = {r.id for r in self.records[-keep_recent:]}
        for r in self.records[:-keep_recent]:
            v = self._feat_cache.get(r.id)
            if v is None or v[0] is None:
                continue
            pending = r.decision == "DOUBT" and r.review.get("final") not in ("GOOD", "DEFECT", "GHOST_CHECKED")
            if not pending and r.id not in recent:
                self._feat_cache[r.id] = (None, None, v[2])

    def _live_pass_line(self) -> float:
        """Review-budget autopilot: if the live share of parts sent to a person exceeds the budget,
        raise the pass line (never above the fail line) to the score quantile that fits the budget.
        The parts that still go to a person are always the riskiest ones below the fail line."""
        pol = self.cal.policy
        if not getattr(self, "autopilot", True):
            return pol.tau_pass
        recent = [r.score for r in self.records if not r.ghost][-60:]
        if len(recent) < 20:
            return pol.tau_pass
        recent = np.array(recent)
        budget = getattr(self, "budget", 0.10)
        fail_frac = float(np.mean(recent > pol.tau_fail))
        if fail_frac > 0.05:
            # A defect-heavy batch (a demo tray, a bad reel): the doubt band is full of real defects. Widening the
            # pass zone now would let them through, so safety wins over the review budget.
            return pol.tau_pass
        q = float(np.clip(1 - 0.9 * budget - fail_frac, 0.0, 1.0))
        cap = pol.tau_pass + 0.5 * (pol.tau_fail - pol.tau_pass)  # never more than halfway into the doubt band
        return float(min(max(pol.tau_pass, np.quantile(recent, q)), cap))

    def _explain(self, decision, reason, score, pol, novelty_p, h, hive, pass_line=None, hold_reason=None) -> str:
        tp = pass_line if pass_line is not None else pol.tau_pass
        if decision == "HOLD":
            return (f"HOLD: {hold_reason}. I give no automatic verdict; the part waits on the belt until it can be "
                    f"judged safely.")
        if hive:
            return (f"FAIL: matches the '{hive['label']}' defect learned at {hive['from']} "
                    f"(similarity {hive['similarity']:.2f}). Shared as a privacy-preserving fingerprint.")
        if decision == "PASS":
            return (f"PASS: every region is within what I learned from {len(self.ref_images)} good parts "
                    f"(score {score:.3f} <= {tp:.3f}).")
        if decision == "FAIL":
            return (f"FAIL: a region is far outside good-part appearance (score {score:.3f} > {pol.tau_fail:.3f}, "
                    f"which fewer than {pol.alpha_fr:.0%} of good parts ever reach).")
        return {
            "BAD_IMAGE": "DOUBT: the image itself is unreliable (blur or exposure). Please re-capture before judging.",
            "CONDITIONS_CHANGED": (f"DOUBT: the line looks different from my references (shift alarm, evidence "
                                   f"x{h['martingale']:.0f}). I won't auto-pass until I see 5 confirmed good parts."),
            "NEVER_SEEN": (f"DOUBT: this part is unlike anything I've seen (novelty p={novelty_p:.3f}). "
                           f"I'm asking rather than guessing."),
            "NOT_THIS_BOARD": (f"DOUBT: this does not look like a {self.product.name} board: it may be a different board type, or a defect "
                               "so large the whole board looks different. I do not name parts from the wrong map and I will not pass it; "
                               "a person checks it."),
            "BORDERLINE": (f"DOUBT: score {score:.3f} sits between my pass line {tp:.3f} and fail line "
                           f"{pol.tau_fail:.3f}. A human decides; I'll learn from it."),
        }.get(reason, "DOUBT")

    def _case_law(self, g, dist, img: Image.Image, hot: dict):
        cls = g.cls[0]
        sims = (cls @ self.gref.cls.T).cpu().numpy()
        nearest = np.argsort(-sims)[:2]
        prec = [{"kind": "reference", "label": "Closest good part", "similarity": round(float(sims[i]), 3),
                 "thumb": b64(self.ref_images[i], 112)} for i in nearest]
        decided = [r for r in self.records if r.review.get("final") in ("GOOD", "DEFECT") and r.id in getattr(self, "_feat_cache", {})]
        if decided:
            cs = torch.stack([self._feat_cache[r.id][2] for r in decided])
            s2 = (cls @ cs.T).cpu().numpy()
            j = int(np.argmax(s2))
            r = decided[j]
            prec.append({"kind": "precedent", "label": f"{r.review['final'].title()} - decided by {r.review.get('by', 'inspector')}",
                         "record": r.id, "similarity": round(float(s2[j]), 3), "image": r.image_url})
        # counterfactual: what the worst patch "should" look like
        h, w = self.mem.hw
        pidx = int(dist[0].argmax())
        q = g.feats[0, pidx]
        bank_sim = q @ self.mem.bank.T if self.mem.bank.dtype == q.dtype else q.half() @ self.mem.bank.T
        j = int(bank_sim.argmax())
        src = int(self.mem.bank_src[j]) // (5 if self.mem.augment_refs else 1)
        src = min(src, len(self.ref_images) - 1)
        cf = {"query": b64(crop_pct(img, hot["x"], hot["y"]), 128),
              "reference": b64(crop_pct(self.ref_images[src], hot["x"], hot["y"]), 128),
              "text": "This region would pass if it looked like this one from a verified good part."}
        return prec, cf

    # ================================================================== ELECTRONICS: COMPONENT-LEVEL INSPECTION
    @property
    def electronics(self) -> bool:
        return self.product.source == "Upload" or self.product.name.lower().startswith("pcb")

    def ensure_board(self, wait: bool = False) -> None:
        """Build the component map (golden board, components, per-component normal ranges) in the background."""
        bm0 = getattr(self, "board", None)
        from .board import MAP_VERSION

        if (bm0 is not None and getattr(bm0, "version", 1) < MAP_VERSION and not getattr(self, "_board_building", False)
                and getattr(self, "ref_images", None) and getattr(self, "loo_maps", None) is not None):
            self.board = bm0 = None  # mapped under older naming rules: map it again
            self.audits = []         # self-test history pointed at the old part names
        if bm0 is not None and getattr(self, "golden", None) is None and getattr(self, "ref_images", None):
            try:  # golden statistics are cheap to rebuild and never saved
                from .golden import GoldenStats

                self.golden = GoldenStats.build(bm0, self.ref_images)
                self.golden_url = save(self.golden.golden_image(), f"{self.id}/golden.jpg")
            except Exception:
                pass
        if bm0 is not None and self.product.source == "Upload" and len(bm0.components) < 8:
            self.board = None  # an earlier, looser rule mapped a non-board upload: drop it
            return
        if getattr(self, "board", None) is not None and not getattr(self, "_board_calibrated", False) and not getattr(self, "_board_building", False):
            def recal():  # a line saved before board-only scoring existed
                try:
                    with self.lock:
                        self._board_recalibrate()
                    self.emit("board.recalibrated", message="Recalibrated on the board only: the mat around it no longer counts",
                              policy=self.cal.policy.to_dict())
                except Exception as e:
                    self.emit("board.error", message=f"Board-only recalibration failed: {e}")
            threading.Thread(target=recal, daemon=True).start()
            return
        if not self.electronics or getattr(self, "board", None) is not None or getattr(self, "_board_building", False):
            return
        self._board_building = True

        def run():
            from .board import BoardMap

            _BOARD_BUILDS.acquire()  # one map at a time: several at once exhaust memory on a laptop
            try:
                self.emit("board.building", message="Finding every component on the golden board...")
                calib = []
                pool = [x for x in self.spare_good if x.label == 0][:40] if self.product.source != "Upload" else []
                for x in pool:  # separate good boards: never references, never inspected
                    im = x.image()
                    with self.lock:
                        g, dist, _ = self.mem.inspect([im])
                        calib.append((im, self.mem.anomaly_maps(dist, g.fg, 256)[0]))
                bm = BoardMap.build(self.ref_images, list(self.loo_maps), calib or None)
                if len(bm.components) < (8 if self.product.source == "Upload" else 3):
                    self.emit("board.skipped", message="This does not look like a circuit board: component check off")
                    self.board = None
                    return
                self.board = bm
                self.board_box3d = self._board_boxes(bm)
                try:
                    from .golden import GoldenStats

                    self.golden = GoldenStats.build(bm, self.ref_images)
                    self.golden_url = save(self.golden.golden_image(), f"{self.id}/golden.jpg")
                except Exception as e:
                    self.emit("board.error", message=f"Golden-board statistics failed: {e}")
                with self.lock:
                    self._board_recalibrate()
                self.emit("board.recalibrated", message="Recalibrated on the board only: the mat around it no longer counts",
                          policy=self.cal.policy.to_dict())
                kinds = ", ".join(f"{v} {k}" for k, v in sorted(bm.public()["kinds"].items(), key=lambda kv: -kv[1]))
                self.emit("board.ready", message=f"Mapped {len(bm.components)} components ({kinds}); calibrated on {bm.calibration}",
                          board=self.board_public())
            except Exception as e:
                self.emit("board.error", message=f"Component map failed: {e}")
            finally:
                self._board_building = False
                _BOARD_BUILDS.release()

        if wait:
            run()
        else:
            threading.Thread(target=run, daemon=True, name=f"board-{self.id}").start()

    def _board_boxes(self, bm) -> dict:
        """Each component as a 3D box on the relief (same frame: the relief and the golden board both come from
        the first reference photo)."""
        cloud = getattr(self, "twin_cloud", None)
        out = {}
        if not cloud or not cloud.get("relief"):
            return out
        pos = np.asarray(cloud["positions"], np.float32).reshape(-1, 3)
        n = int(cloud["grid"])
        H, W = bm.golden.shape[:2]
        tall = {"connector": 0.16, "IC": 0.07, "transistor": 0.05, "capacitor": 0.05, "inductor": 0.06, "diode / LED": 0.04,
                "resistor": 0.03, "hole / pad": 0.01, "metal part": 0.06, "other": 0.04}
        for c in bm.components:
            x, y, w, h = c.bbox
            cols = np.clip(np.array([x, x + w]) / W * (n - 1), 0, n - 1).astype(int)
            rows = np.clip(np.array([y, y + h]) / H * (n - 1), 0, n - 1).astype(int)
            patch = pos.reshape(n, n, 3)[rows[0]:rows[1] + 1, cols[0]:cols[1] + 1].reshape(-1, 3)
            if not len(patch):
                continue
            x0, x1 = float(patch[:, 0].min()), float(patch[:, 0].max())
            z0, z1 = float(patch[:, 2].min()), float(patch[:, 2].max())
            surf = float(np.median(patch[:, 1]))  # data y = -height*depth (towards the camera is more negative)
            t = tall.get(c.kind, 0.04)
            out[c.id] = {"center": [(x0 + x1) / 2, surf - t / 2, (z0 + z1) / 2], "size": [max(0.01, x1 - x0), t, max(0.01, z1 - z0)]}
        return out

    def board_public(self) -> dict | None:
        bm = getattr(self, "board", None)
        if bm is None:
            return {"status": "building" if getattr(self, "_board_building", False) else "none", "electronics": self.electronics}
        from .board import STATUS_TEXT

        pub = bm.public()
        boxes = getattr(self, "board_box3d", None) or {}
        for c in pub["components"]:
            c["box3d"] = boxes.get(c["id"])
        # how each component has fared on this line (real parts only)
        fails: dict = {}
        n = 0
        for r in self.records:
            if r.board is None or r.synthetic or r.ghost:
                continue
            n += 1
            for f in r.board.get("faults", []):
                fails.setdefault(f["id"], {}).setdefault(f["status"], 0)
                fails[f["id"]][f["status"]] += 1
        for c in pub["components"]:
            c["history"] = fails.get(c["id"], {})
        return {"status": "ready", "electronics": True, **pub, "golden": b64(Image.fromarray(bm.golden), 768),
                "calibration": bm.calibration, "boardsChecked": n, "statusText": STATUS_TEXT,
                "classifier": _clf_report()}

    def _board_check(self, bm, shown: Image.Image, hm: np.ndarray, rec) -> dict:
        d = bm.diagnose(shown, hm, self.cal.policy.tau_pass)
        aligned = d.pop("_aligned", None)
        kinds = {c.id: c.kind for c in bm.components}
        tp = self.cal.policy.tau_pass
        faults = []
        for r in d["components"]:
            if r["status"] == "OK":
                continue
            m = r["measured"]
            heat_ok = float(m.get("heat", 0)) > 0.8 * tp  # the patch memory also sees something here
            overwhelming = (r["status"] == "MISSING" and float(m.get("bodyFrac", 1)) < 0.08) or \
                           (r["status"] == "BURNT" and float(m.get("dL", 0)) < -35 and m.get("burntStrong"))
            strength = float(m.get("heat", 0)) / max(tp, 1e-9) + (1.0 if overwhelming else 0.0)
            faults.append({**r, "kind": kinds[r["id"]], "_corroborated": heat_ok or overwhelming, "_overwhelming": overwhelming, "_strength": strength})
        faults += [{**e, "kind": "-"} for e in d["extra"]]
        # A component is called faulty only when two independent measurements agree (its own geometry/colour check AND
        # the patch-memory heatmap), or the geometric evidence is overwhelming. Uncorroborated flags, flags on a passed
        # board, and anything beyond the 4 strongest become 'watch' notes: the calibrated board verdict decides.
        faults.sort(key=lambda f: -f.get("_strength", 0))
        # Component evidence can raise a PASS to DOUBT (never to FAIL): a part whose body is clearly gone or clearly
        # charred is overwhelming geometric evidence even when the whole-board score stays under the pass line.
        esc = [f for f in faults if f.get("_overwhelming") and f["status"] in ("MISSING", "BURNT")]
        if rec.decision == "PASS" and esc:
            rec.decision, rec.doubt_reason, rec.routing = "DOUBT", "COMPONENT", ROUTING["DOUBT"]
            rec.uncertainty = max(rec.uncertainty, 0.7)
            rec.explanation += " The component check disagrees with the overall score: " + ", ".join(
                f"{f['id']} looks {f['status'].lower()}" for f in esc[:3]) + ". A person decides."
        n_fault = 0
        for f in faults:
            strong = f.pop("_corroborated", True)
            f.pop("_overwhelming", None)
            f.pop("_strength", None)
            if rec.decision == "PASS" or not strong or n_fault >= 4:
                f["level"] = "watch"
            else:
                f["level"] = "fault"
                n_fault += 1
        # tie each image region to the component it sits on
        for g in rec.regions or []:
            cx, cy = g["centroid"]
            hit = None
            for r in d["components"]:
                c = next(c for c in bm.components if c.id == r["id"])
                x, y, w, h = c.bbox
                H, W = bm.golden.shape[:2]
                gx, gy = cx * W, cy * H
                if x - 6 <= gx <= x + w + 6 and y - 6 <= gy <= y + h + 6:
                    hit = c
                    break
            if hit is not None:
                g["component"] = {"id": hit.id, "kind": hit.kind}
        from . import smt

        chip_crops = {}
        chips_here = [c for c in bm.components if c.kind in ("IC", "transistor") and c.area > 300]
        if chips_here:  # full-resolution close-ups of every chip, so its marking can be read later
            from .board import align, to_work
            from .chips import _crop

            a_full = aligned if aligned is not None else align(to_work(shown), bm.golden)[0]
            for c in chips_here:
                chip_crops[c.id] = save(_crop(a_full, c.bbox), f"{self.id}/{rec.id}_chip_{c.id}.jpg", 92)

        for f in faults:  # where it likely started and how to repair it travel with every fault
            stage, origin, cause, check = smt.ROOT.get(f["status"], ("aoi_post", "-", "-", "-"))
            f.update(stage=stage, origin=origin, cause=cause, check=check,
                     action=smt.ACTION.get(f["status"], "Inspect {id}").format(id=f["id"], kind=f.get("kind", "part")))
        m = {r["id"]: [round(float(r["measured"].get("offset", 0)), 2), round(float(r["measured"].get("dL", 0)), 2)] for r in d["components"]}
        photo = save(Image.fromarray(aligned), f"{self.id}/{rec.id}_aligned.jpg", 85) if aligned is not None else None
        return {"checked": len(d["components"]), "ok": d["summary"].get("OK", 0), "faults": faults, "m": m, "chipCrops": chip_crops,
                "aligned": photo,
                "summary": d["summary"]}

    def _sentinel_maybe(self) -> None:
        """Every few real boards, plant one known fault on a held-out good board and inspect it (in the background)
        so the live catch rate per fault type is always measured on this line as it is now."""
        n_real = sum(1 for r in self.records if not r.synthetic and not r.ghost)
        if getattr(self, "board", None) is None or n_real % 5 != 0 or getattr(self, "_sentinel_busy", False):
            return
        from . import sentinel

        self._sentinel_busy = True

        def run():
            try:
                sentinel.audit(self)
                from . import persist
                persist.save_async(self)
            except Exception as e:
                self.emit("sentinel.error", message=f"Sentinel audit failed: {e}")
            finally:
                self._sentinel_busy = False
        threading.Thread(target=run, daemon=True, name=f"sentinel-{self.id}").start()

    def fault_lab(self, comp_id: str, kind: str) -> "Record":
        """Rehearsal: plant a known fault on one component of a held-out good board and inspect it for real.
        The part is marked synthetic so it never enters the real performance numbers."""
        from .board import FAULTS, plant_fault

        bm = getattr(self, "board", None)
        if bm is None:
            raise ValueError("The component map is not ready yet")
        if kind not in FAULTS:
            raise ValueError(f"fault must be one of {FAULTS}")
        pool = [x for x in self.eval_pool if x.label == 0] or self.spare_good
        rng = np.random.default_rng()
        base = pool[int(rng.integers(len(pool)))].image()
        img = plant_fault(base, bm, comp_id, kind, rng)
        rec = self.inspect(img, truth=1, defect_type=f"synthetic {kind.replace('_', ' ')} on {comp_id}")
        rec.synthetic = f"{kind} on {comp_id}"
        rec.truth = None  # keep it out of escape / false-reject statistics
        self.emit("line.record", record=rec.to_dict())
        return rec

    # ================================================================== DEFECT REGIONS + 3D CALLOUTS
    def _fg256(self, g, i: int = 0) -> np.ndarray:
        f = g.fg[i].reshape(self.mem.hw).cpu().numpy().astype(np.uint8) * 255
        return np.asarray(Image.fromarray(f).resize((256, 256), Image.NEAREST)) > 0

    def region_library(self) -> list:
        """Fingerprint of the strongest region of every labelled defect example of this product."""
        lib = getattr(self, "_region_lib", None)
        if lib is not None:
            return lib
        lib = []
        ex = [s_ for s_ in self.known_defects if s_.defect_type and s_.defect_type not in ("anomaly", "defect", "uploaded defect")]
        if ex:
            g, dist, _ = self.mem.inspect([s_.image() for s_ in ex])
            maps = self.mem.anomaly_maps(dist, g.fg, 256)
            for i, (s_, hm) in enumerate(zip(ex, maps)):
                c = regionlib.candidates(hm, self.cal.policy.tau_pass, keep_rel=0.0, max_regions=1)
                if not c:
                    continue
                sig = regionlib.signature(self.mem, g.feats[i], c[0][0])
                for t in s_.defect_type.split(","):
                    if t.strip():
                        lib.append((t.strip(), sig))
        self._region_lib = lib
        return lib

    def analyse_regions(self, g, dist, hm: np.ndarray, shown: Image.Image, rid: str | None = None) -> list[dict]:
        pol = self.cal.policy
        regs = regionlib.find_regions(hm, shown, self._fg256(g), pol.tau_pass, pol.tau_fail,
                                      mem=self.mem, feats=g.feats[0], library=self.region_library())
        out = []
        for r in regs:
            crop = r.pop("_crop")
            r.pop("_mask")
            if rid:
                r["crop"] = save(crop, f"{self.id}/{rid}_{r['id']}.jpg")
            r["anchor"] = self._anchor_3d(g, r["centroid"])
            out.append(r)
        return out

    def _anchor_3d(self, g, centroid) -> list | None:
        """Where a 2D defect region sits on the 3D twin (posed views) or on the 2.5D relief (single view)."""
        cloud = getattr(self, "twin_cloud", None)
        if not cloud:
            return None
        pos = np.asarray(cloud["positions"], np.float32).reshape(-1, 3)
        if self.twin is None:  # relief: a regular grid in image order
            n = cloud.get("grid") or int(round(np.sqrt(len(pos))))
            col = min(n - 1, max(0, int(round(centroid[0] * (n - 1)))))
            row = min(n - 1, max(0, int(round(centroid[1] * (n - 1)))))
            return [round(float(v), 4) for v in pos[row * n + col]]
        if not hasattr(self, "_pose_lib"):
            lib = self.ref_samples
            self._pose_lib = (self.bb([s_.image() for s_ in lib]).cls, [s_.pose for s_ in lib])
        cls_lib, poses = self._pose_lib
        pose = poses[int((g.cls[0] @ cls_lib.T).argmax())]
        pts = torch.from_numpy(pos).to(self.twin.xyz.device if self.twin.xyz is not None else "cpu")
        u, v, z, _ = Twin.project(pts, pose, self.product.fov_x, (256, 256))
        d2 = (u - centroid[0] * 256) ** 2 + (v - centroid[1] * 256) ** 2
        near = (d2 < 36) & (z > 0)  # within 6 px of the region centre, in front of the camera
        if not bool(near.any()):
            k = int(d2.argmin())
        else:
            zz = torch.where(near, z, torch.full_like(z, float("inf")))
            k = int(zz.argmin())  # the front-most surface point the camera actually saw
        return [round(float(x), 4) for x in pos[k]]

    def _project_to_twin(self, g, heat: np.ndarray) -> list | None:
        """Estimate the pose by retrieving the closest posed view, then paint heat onto the twin."""
        if not hasattr(self, "_pose_lib"):
            lib = self.ref_samples
            self._pose_lib = (self.bb([s.image() for s in lib]).cls, [s.pose for s in lib])
        cls_lib, poses = self._pose_lib
        k = int((g.cls[0] @ cls_lib.T).argmax())
        pose = poses[k]
        pts = torch.tensor(np.array(self.twin_cloud["positions"]).reshape(-1, 3), dtype=torch.float32,
                           device=self.twin.xyz.device)
        nrm = torch.tensor(np.array(self.twin_cloud["normals"]).reshape(-1, 3), dtype=torch.float32, device=pts.device)
        u, v, z, _ = Twin.project(pts, pose, self.product.fov_x, (256, 256))
        cam = torch.from_numpy(pose[:3, 3]).float().to(pts.device)
        facing = (torch.nn.functional.normalize(cam - pts, dim=-1) * nrm).sum(-1)
        ok = (u >= 0) & (u < 256) & (v >= 0) & (v < 256) & (facing > 0.1)
        hm = torch.from_numpy(heat).float().to(pts.device)
        val = torch.zeros(len(pts), device=pts.device)
        val[ok] = hm[v[ok].long().clamp(0, 255), u[ok].long().clamp(0, 255)]
        tp = self.cal.policy.tau_pass
        return (val / max(tp * 2, 1e-9)).clamp(0, 1).cpu().numpy().round(3).tolist()

    # ================================================================== REVIEW + FEEDBACK FIREWALL
    def review(self, rid: str, verdict: str, reviewer: str, role: str) -> dict:
        with self.lock:
            r = next(x for x in self.records if x.id == rid)
            rv = self.reviewers.setdefault(reviewer, {"ghosts": 0, "ghostCorrect": 0, "reviews": 0})
            rv["reviews"] += 1
            if r.ghost and r.truth is not None:  # known-answer check
                rv["ghosts"] += 1
                rv["ghostCorrect"] += int((verdict == "DEFECT") == bool(r.truth))
            reliability = (rv["ghostCorrect"] + 1) / (rv["ghosts"] + 1)  # Laplace-smoothed
            r.review.setdefault("votes", []).append({"by": reviewer, "role": role, "verdict": verdict,
                                                     "reliability": round(reliability, 2), "at": _now()})
            votes = r.review["votes"]
            distinct = {v["by"] for v in votes}
            agree = len({v["verdict"] for v in votes}) == 1
            weight = sum(v["reliability"] for v in votes)
            if r.ghost:
                r.review["final"] = "GHOST_CHECKED"
                status = "Ghost check recorded (reviewer reliability updated)"
            elif len(distinct) >= 2 and agree and weight >= 1.2:
                r.review["final"] = verdict
                r.review["by"] = " + ".join(sorted(distinct))
                learned = self._learn(r, verdict)
                status = f"Two-person rule satisfied - {learned}"
            elif not agree:
                r.review["final"] = "DISPUTED"
                status = "Reviewers disagree - escalated to Quality Manager; nothing learned"
                STATION.raise_alert(f"Reviewers disagree on {r.id}", "Two reviewers gave opposite verdicts; nothing was "
                                    "learned.", "WARNING", "DISPUTE", self.id, "Quality manager decides", dedupe=False)
            else:
                r.review["final"] = "PENDING_SECOND"
                status = "Awaiting a second, independent reviewer before I learn from this"
            r.review["status"] = status
            if rv["ghosts"] >= 3 and reliability < 0.7:
                STATION.raise_alert(f"Reviewer {reviewer} may be unreliable",
                                    f"Correct on {rv['ghostCorrect']} of {rv['ghosts']} known-answer checks.", "WARNING",
                                    "REVIEWER", self.id, "Pair this reviewer with a second check")
            STATION.log(reviewer, role, "review", r.id, {"verdict": verdict, "status": status})
            self._check_overload()
            self.emit("line.review", record=r.to_dict(), reviewer=self.reviewers[reviewer], message=status)
            return {"record": r.to_dict(), "status": status, "reviewer": {**rv, "reliability": round(reliability, 2)}}

    def _learn(self, r: Record, verdict: str) -> str:
        feats, dist, cls = self._feat_cache.get(r.id, (None, None, None))
        if feats is None:
            return "recorded the verdict (part too old to learn patch details from)"
        if verdict == "GOOD":
            img = Image.open(_media_path(r.image_url)).convert("RGB")
            n = self.mem.add([img])
            return f"added {n} patch memories (append-only, nothing forgotten)"
        fp = deviation_signature(self.mem, feats, dist)
        label = r.defect_type if r.defect_type and r.defect_type != "good" else "Confirmed defect"
        self.learned_defects.append({"label": label, "vec": fp, "from": self.plant, "record": r.id})
        return f"learned defect fingerprint '{label}'"

    def review_queue(self, limit: int = 20) -> list[dict]:
        """Active learning: order the parts waiting for a person by how much their answer would teach.
        Value = closeness to the decision boundary + novelty + difference from parts already answered
        (greedy, so the top few cover different situations instead of five copies of one)."""
        pend = [r for r in self.records if r.decision == "DOUBT"
                and r.review.get("final") not in ("GOOD", "DEFECT", "GHOST_CHECKED")]
        if not pend:
            return []
        cache = getattr(self, "_feat_cache", {})
        chosen = [cache[r.id][2] for r in self.records if r.review.get("final") in ("GOOD", "DEFECT") and r.id in cache]
        out, left = [], list(pend)
        while left and len(out) < limit:
            best, best_v, parts = None, -1.0, (0.0, 0.0, 0.0)
            for r in left:
                boundary = r.uncertainty
                novelty = 1 - min(1.0, r.novelty_p * 5)
                div = 1.0
                if chosen and r.id in cache:
                    div = float(1 - (torch.stack(chosen) @ cache[r.id][2]).max().clamp(0, 1))
                v = 0.5 * boundary + 0.25 * novelty + 0.25 * min(1.0, div * 8)
                if v > best_v:
                    best, best_v, parts = r, v, (boundary, novelty, div)
            left.remove(best)
            if best.id in cache:
                chosen.append(cache[best.id][2])
            why = ("right on my decision line" if parts[0] > 0.85 else
                   "unlike anything I've seen" if parts[1] > 0.6 else
                   "unlike parts already answered" if parts[2] > 0.06 else "borderline")
            out.append({"id": best.id, "teachValue": round(best_v, 3), "why": why})
        return out

    # ================================================================== MEMORY + FORGETTING
    def _probe_set(self):
        goods = [s for s in self.eval_pool if s.label == 0][:12] or self.spare_good[:12]
        defects = [s for s in self.eval_pool if s.label == 1][:8] or self.known_defects[:8]
        return goods, defects

    def _silent_scores(self, images) -> np.ndarray:
        out = []
        for i in range(0, len(images), 8):
            g, d, _ = self.mem.inspect(images[i:i + 8])
            out += self._weighted_score(d, g.fg).tolist()
        return np.array(out)

    def _probe_baseline(self) -> None:
        goods, defects = self._probe_set()
        self._probe_imgs = ([s.image() for s in goods], [s.image() for s in defects])
        pol = self.cal.policy
        gs, ds = self._silent_scores(self._probe_imgs[0]), self._silent_scores(self._probe_imgs[1]) if defects else np.zeros(0)
        self.forgetting = [{"t": _now(), "label": "Learned the product", "goodsPassed": int((gs <= pol.tau_fail).sum()),
                            "goods": len(gs), "defectsFlagged": int((ds > pol.tau_pass).sum()), "defects": len(ds),
                            "meanGoodScore": round(float(gs.mean()), 4) if len(gs) else None}]

    def forgetting_check(self, label: str = "Check") -> dict:
        """Re-inspect the same original parts under the ORIGINAL conditions: did learning anything new
        (adaptation, confirmed parts, hive lessons) make me worse at what I already knew?"""
        with self.lock:
            if not hasattr(self, "_probe_imgs"):
                self._probe_baseline()
            pol = self.cal.policy
            gi, di = self._probe_imgs
            gs = self._silent_scores(gi)
            ds = self._silent_scores(di) if di else np.zeros(0)
            row = {"t": _now(), "label": label, "goodsPassed": int((gs <= pol.tau_fail).sum()), "goods": len(gs),
                   "defectsFlagged": int((ds > pol.tau_pass).sum()), "defects": len(ds),
                   "meanGoodScore": round(float(gs.mean()), 4) if len(gs) else None}
            self.forgetting.append(row)
            return {"history": self.forgetting, "latest": row, "baseline": self.forgetting[0]}

    def memory_summary(self) -> dict:
        reviewed = [r for r in self.records if r.review.get("final") in ("GOOD", "DEFECT")]
        pending = [r for r in self.records if len(r.review.get("votes", [])) == 1 and r.review.get("final") == "PENDING_SECOND"]
        return {
            "normal": {"references": len(getattr(self, "ref_images", [])), "patchMemories": int(len(self.mem.bank)),
                       "learnedGood": [{"id": r.id, "image": r.image_url, "by": r.review.get("by")} for r in reviewed
                                       if r.review["final"] == "GOOD"][-12:],
                       "adaptations": getattr(self, "adaptations", [])},
            "defect": {"real": len(self.known_defects), "imagined": len(getattr(self, "imagined_scores", [])),
                       "learned": [{"label": d["label"], "from": d["from"], "record": d.get("record"),
                                    "image": next((r.image_url for r in self.records if r.id == d.get("record")), None)}
                                   for d in self.learned_defects],
                       "hive": [{"label": f["label"], "from": f["from"]} for f in self.hive_library]},
            "pending": [{"id": r.id, "image": r.heat_url, "votes": r.review.get("votes", [])} for r in pending][-12:],
            "forgetting": getattr(self, "forgetting", []),
        }

    def trace(self, rid: str) -> dict:
        """Walk one inspected part through every pipeline stage with its real intermediate outputs."""
        from .visual import MEDIA

        r = next((x for x in self.records if x.id == rid), None)
        if r is None:
            raise KeyError(rid)
        img = Image.open(MEDIA / r.image_url.replace("/media/", "", 1)).convert("RGB")
        with self.lock:
            g, dist, _ = self.mem.inspect([img])
        h, w = g.hw
        fg = g.fg[0].reshape(h, w).float().cpu().numpy()
        fg_img = Image.fromarray((fg * 255).astype(np.uint8)).resize((384, 384), Image.NEAREST)
        base = np.asarray(img.resize((384, 384))).astype(np.float32) / 255
        m = np.asarray(fg_img)[..., None] / 255.0
        fg_overlay = Image.fromarray(((base * (0.35 + 0.65 * m) + np.array([0.36, 0.78, 0.71]) * 0.25 * m) * 255).clip(0, 255).astype(np.uint8))
        pol = self.cal.policy
        return {
            "record": r.to_dict(),
            "stages": [
                {"key": "see", "title": "See", "what": "Capture the part (dataset feed or upload) under the line's current conditions.",
                 "image": r.image_url, "facts": {"conditions changed": not Conditions(**r.conditions).is_identity(),
                                                   "camera": "offline" if "camera" in STATION.faults else "online"}},
                {"key": "quality", "title": "Image check", "what": "Refuse to judge images that cannot be trusted.",
                 "facts": {**(r.quality or {}), "verdict": "HOLD" if r.decision == "HOLD" else "usable"}},
                {"key": "understand", "title": "Understand", "what": "DINOv2 turns the photo into patch features; the object is separated from the background.",
                 "image": b64(fg_overlay, 384), "facts": {"patches on the part": int(g.fg[0].sum()), "patch grid": f"{h}x{w}"}},
                {"key": "compare", "title": "Compare", "what": "Each patch is compared with its nearest memory of a good part.",
                 "image": r.heat_url, "facts": {"memories searched": int(len(self.mem.bank)), "most unusual spot": r.hotspot}},
                {"key": "components", "title": "Components", "what": "Electronics: every component checked against its own normal range from good boards.",
                 "facts": ({"checked": r.board["checked"], "as on good boards": r.board["ok"],
                            **{f["id"]: f"{f['status'].lower()} · {f['why'][0] if f.get('why') else ''}" for f in r.board["faults"]}}
                           if getattr(r, "board", None) else {"component check": "not available for this part"})},
                {"key": "locate", "title": "Locate", "what": "Flagged parts: split the heatmap into regions, measure, name and pin each one in 3D.",
                 "image": (r.regions or [{}])[0].get("crop") if getattr(r, "regions", None) else None,
                 "facts": {"regions": len(getattr(r, "regions", None) or []),
                           **{g["id"]: f"{g['label']} · {g['severity']} · {g['areaPct']}% of part" for g in (getattr(r, "regions", None) or [])}}
                 if r.decision in ("FAIL", "DOUBT") else {"regions": "not needed (part passed or was held)"}},
                {"key": "doubt", "title": "Doubt", "what": "Calibrated lines decide whether I may act alone.",
                 "facts": {"unusualness": r.score, "pass line": r.pass_line, "fail line": round(pol.tau_fail, 5),
                           "p-value vs good parts": r.p_value, "novelty p": r.novelty_p, "shift evidence": r.martingale}},
                {"key": "decide", "title": "Decide", "what": "Verdict and where the part goes on the line.",
                 "facts": {"decision": r.decision, "reason": r.doubt_reason or r.hold_reason, "routing": r.routing}},
                {"key": "learn", "title": "Learn", "what": "People review doubts; two must agree before I learn.",
                 "facts": {"review": r.review.get("status") or "not reviewed", "votes": len(r.review.get("votes", []))}},
            ],
            "timings": r.stage_ms, "latencyMs": r.latency_ms,
        }

    def demo_image(self, want: str) -> tuple[Image.Image, int | None, str | None]:
        """Pick a real part that demonstrates an outcome (scored silently first, then inspected for real)."""
        if want == "novel":  # a part with something it has never seen: a foreign fibre lying on it
            base = (self.spare_good or [s for s in self.eval_pool if s.label == 0] or self.ref_samples)[0].image()
            return imagine(base, "fiber", 0.22 * base.width, np.random.default_rng(7)).image, 1, "foreign object"
        pool = [s for s in self.eval_pool if s.label == (0 if want == "good" else 1)]
        if not pool:
            pool = self.spare_good if want == "good" else self.known_defects
        cand = pool[:10]
        sc = self._silent_scores([s.image() for s in cand])
        s = cand[int(np.argmin(sc)) if want == "good" else int(np.argmax(sc))]
        return s.image(), s.label if s.label >= 0 else None, s.defect_type

    # ================================================================== ADAPT (domain shift)
    def adapt(self, n: int = 5) -> dict:
        with self.lock:
            pool = self.spare_good[:n] if len(self.spare_good) >= n else (self.ref_samples * 2)[:n]
            imgs = [perturb(s.image(), self.conditions, seed=5000 + i) for i, s in enumerate(pool)]
            self.spare_good = self.spare_good[n:]
            before = self.cal.policy.to_dict()
            # The new photos join the MEMORY (so parts under the new conditions look familiar again),
            # but NOT the calibration: 5 non-exchangeable images would dominate a max-based conformal
            # threshold and could push the fail line up until defects pass. The thresholds stay those
            # calibrated on the original exchangeable references.
            added = self.mem.add(imgs)
            self.ref_images = self.ref_images + imgs
            self.gref = self.bb(self.ref_images)
            self.global_calib = global_nonconformity(self.gref.cls, self.gref.cls, exclude_self=True).cpu().numpy()
            self.guard.reset(self.global_calib, self.loo)
            self._alarm_announced = False
            self._forecast_base = None
            msg = f"Adapted from {n} confirmed photos under the new conditions ({added:,} new memories); old knowledge kept"
            STATION.resolve_category("SHIFT", self.id)
            self.adaptations = getattr(self, "adaptations", []) + [{"t": _now(), "photos": n, "memories": added,
                                                                     "conditions": self.conditions.__dict__.copy()}]
            self.emit("shift.adapted", message=msg, policy=self.cal.policy.to_dict(), before=before)
            return {"message": msg, "policy": self.cal.policy.to_dict()}

    def set_conditions(self, c: dict) -> dict:
        with self.lock:
            self.conditions = Conditions(**{**Conditions().__dict__, **c})
            self.emit("chaos.conditions", conditions=self.conditions.__dict__, message="Line conditions changed")
            return self.conditions.__dict__

    # ================================================================== TRUST
    def trust_curve(self, prevalence: float = 0.03, parts_per_shift: int = 4000, review_sec: float = 12,
                    cost_escape: float = 2500, cost_review: float = 4) -> dict:
        defects = np.concatenate([self.known_scores, self.imagined_scores])
        good = self.loo
        tau_fail = self.cal.policy.tau_fail
        rows = []
        for e in [0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.12, 0.2, 0.3, 0.4, 0.5, 0.6]:
            tp = min(lower_quantile(defects, e), tau_fail)
            rg = float(np.mean((good > tp) & (good <= tau_fail)))
            rd = float(np.mean((defects > tp) & (defects <= tau_fail)))
            esc = float(np.mean(defects <= tp))
            review = (1 - prevalence) * rg + prevalence * rd
            ppm = prevalence * esc * 1e6
            rows.append({"targetEscape": e, "tauPass": tp, "reviewRate": review, "escapeRate": esc,
                         "escapeUpper90": wilson_upper(int(np.sum(defects <= tp)), len(defects)),
                         "ppm": ppm, "inspectorHours": review * parts_per_shift * review_sec / 3600,
                         "rupeesPerShift": parts_per_shift * (prevalence * esc * cost_escape + review * cost_review)})
        naive_esc = float(np.mean(defects <= self.tau_naive))
        return {"rows": rows, "naive": {"escapeRate": naive_esc, "ppm": prevalence * naive_esc * 1e6,
                                        "rupeesPerShift": parts_per_shift * prevalence * naive_esc * cost_escape},
                "assumptions": {"prevalence": prevalence, "partsPerShift": parts_per_shift, "reviewSeconds": review_sec,
                                "costPerEscape": cost_escape, "costPerReview": cost_review},
                "calibration": {"good": len(good), "realDefects": len(self.known_scores), "imaginedDefects": len(self.imagined_scores)}}

    def set_target(self, target_escape: float, budget: float) -> dict:
        with self.lock:
            self.budget = budget
            self._calibrate(budget=budget, target_escape=target_escape)
            self.emit("trust.policy", policy=self.cal.policy.to_dict(), message="Trust contract updated")
            return self.cal.policy.to_dict()

    def performance(self) -> dict:
        """Live, measured on the stream (ground truth known because the parts come from public datasets)."""
        rec = [r for r in self.records if r.truth is not None and not r.ghost]
        if not rec:
            return {"n": 0}
        s = np.array([r.score for r in rec])
        y = np.array([r.truth for r in rec])
        dec = np.array([r.decision for r in rec])
        nd, ng = max(int(y.sum()), 1), max(int((1 - y).sum()), 1)
        ours = {"escapes": int(((dec == "PASS") & (y == 1)).sum()), "falseRejects": int(((dec == "FAIL") & (y == 0)).sum()),
                "reviewed": int((dec == "DOUBT").sum()), "held": int((dec == "HOLD").sum())}
        nv = np.array([r.naive_decision for r in rec])
        naive = {"escapes": int(((nv == "PASS") & (y == 1)).sum()), "falseRejects": int(((nv == "FAIL") & (y == 0)).sum()),
                 "reviewed": 0}
        rc = risk_coverage(s, y, self.cal.policy.tau_fail) if y.any() and (1 - y).any() else None
        return {"n": len(rec), "defects": int(y.sum()), "good": int((1 - y).sum()), "ours": ours, "naive": naive,
                "ourEscapeRate": ours["escapes"] / nd, "naiveEscapeRate": naive["escapes"] / nd,
                "ourReviewRate": ours["reviewed"] / len(rec), "riskCoverage": rc}

    # ================================================================== FORECAST
    def _update_forecast(self) -> None:
        """Watch how typical ALL parts are (not only passed ones): process wear shows up as a slow rise
        long before parts cross the fail line."""
        raw = [r.score for r in self.records if not r.ghost][-220:]
        # rolling median: wear moves every part, a defect only moves one; the median ignores defects
        series = [float(np.median(raw[max(0, i - 8):i + 1])) for i in range(len(raw))][-200:]
        if len(series) < 8:
            self.forecast = {"ready": False}
            return
        x = np.arange(len(series))
        ewma, a, cur = [], 0.15, float(np.median(series[:9]))  # warm start: no spike from the first part
        for v in series:
            cur = a * v + (1 - a) * cur
            ewma.append(cur)
        w = min(40, len(series))
        slope, _ = np.polyfit(x[-w:], np.array(ewma[-w:]), 1)
        tp = self.cal.policy.tau_pass
        # process baseline = this line's own first 20 parts (SPC-style), not the reference photos
        if getattr(self, "_forecast_base", None) is None and len(series) >= 20:
            self._forecast_base = float(np.median(series[:20]))
        base = self._forecast_base if getattr(self, "_forecast_base", None) is not None else float(np.median(series))
        if ewma[-1] >= tp:
            eta = 0
        elif slope > 1e-7:
            eta = int((tp - ewma[-1]) / slope)
        else:
            eta = None
        drift = (ewma[-1] - base) / max(tp - base, 1e-9)
        status = "STORM_COMING" if eta is not None and eta < 300 and drift > 0.3 else "DRIFTING" if drift > 0.5 else "CLEAR"
        self.forecast = {"ready": True, "ewma": [round(float(v), 5) for v in ewma[-120:]], "tauPass": tp,
                         "baseline": base, "slope": float(slope), "partsUntilStorm": eta,
                         "drift": round(float(drift), 3), "status": status, "hotspot": self._hotspot_trend()}

    def _hotspot_trend(self) -> dict | None:
        cut = 1.2 * float(np.median(self.loo))
        recent = [r for r in self.records[-40:] if not r.ghost and r.score > cut]
        if len(recent) < 8:
            return None
        xs = np.array([r.hotspot["x"] for r in recent])
        ys = np.array([r.hotspot["y"] for r in recent])
        if xs.std() < 0.12 and ys.std() < 0.12:
            return {"x": float(xs.mean()), "y": float(ys.mean()),
                    "message": f"{len(recent)} recent parts show their weak anomaly in the same spot - likely a process "
                               f"cause (tool wear, fixture, nozzle), not random noise."}
        return None

    def wear_stream(self, n: int = 60) -> None:
        """Simulated tool wear: a micro-scratch on good parts grows slowly, part after part."""
        rng = np.random.default_rng(77)
        src = self.spare_good or self.ref_samples
        base = (src * (n // max(len(src), 1) + 1))[:n]
        fg = object_mask(self.ref_images[0])
        center = None
        for i, s in enumerate(base):
            im = s.image()
            size = 0.005 + 0.06 * (i / n) ** 1.4
            if center is None:
                m = object_mask(im)
                ys, xs = np.nonzero(m)
                k = len(xs) // 2
                center = (float(xs[k]), float(ys[k]))
            if size > 0.012:
                im = imagine(im, "scratch", size * im.width, rng, center=center).image
            self.inspect(im, truth=int(size > 0.04), defect_type="tool wear" if size > 0.04 else "good")
            time.sleep(0.05)

    # ================================================================== HIVE
    def share_fingerprints(self, epsilon_noise: float = 0.05) -> list[dict]:
        out = []
        for d in self.learned_defects:
            v = d["vec"] + torch.randn_like(d["vec"]) * epsilon_noise  # privacy noise: no pixels, only 384 numbers
            out.append({"label": d["label"], "from": d["from"], "vec": torch.nn.functional.normalize(v, dim=0)})
        return out

    def receive_fingerprints(self, fps: list[dict]) -> int:
        with self.lock:
            self.hive_library += fps
            STATION.raise_alert(f"{self.product.name}: lessons received from the hive",
                                f"{len(fps)} defect fingerprint(s) from another plant; no images were shared.", "INFO",
                                "HIVE", self.id, dedupe=False)
            self.emit("hive.received", message=f"Received {len(fps)} defect fingerprints from the hive",
                      labels=[f["label"] for f in fps])
            return len(fps)

    def _hive_match(self, g, dist) -> dict | None:
        feats = g.feats[0][g.fg[0]]
        d = dist[0][g.fg[0]]
        q = deviation_signature(self.mem, feats, d)
        best = None
        for f in self.hive_library:
            s = float(q @ f["vec"].to(q.device))
            if best is None or s > best["similarity"]:
                best = {"label": f["label"], "from": f["from"], "similarity": s}
        # require both an anomalous region and a close fingerprint match
        # thresholds measured on VisA capsules: good parts' 90th-percentile similarity is 0.21,
        # good parts' max patch distance stays below ~1.3x the pass line
        if best and best["similarity"] > 0.30 and float(d.max()) > 1.3 * self.cal.policy.tau_pass:
            return best
        return None

    # ================================================================== BLIND-SPOT ATLAS
    def part_mask(self, img: Image.Image, fg_grid: np.ndarray | None = None) -> np.ndarray:
        """Tight silhouette of the part: backbone foreground AND colour-vs-background, cleaned up."""
        import cv2

        col = object_mask(img)
        m = col
        if fg_grid is not None:
            fgm = object_mask(img, fg_grid)
            both = fgm & col
            m = both if both.mean() > 0.04 else fgm
        m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
        cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if cs:  # the part is the biggest solid blob; fill its holes, drop background texture
            big = max(cs, key=cv2.contourArea)
            keep = [c for c in cs if cv2.contourArea(c) > 0.15 * cv2.contourArea(big)]
            m = np.zeros_like(m)
            cv2.drawContours(m, keep, -1, 1, thickness=cv2.FILLED)
        return m.astype(bool)

    def blind_spots(self, grid: int = 7, sizes=(0.02, 0.04, 0.07, 0.11, 0.16), kind: str = "scratch",
                    verify: bool = True) -> dict:
        """Smallest planted defect I catch in each region of the part - measured, not assumed.

        Each planted defect is scored exactly like a live part (leave-one-out: the photo it was planted on is
        removed from my memory first) and only counts as caught if my verdict leaves PASS *and* my heatmap
        points at the planted defect. Regions I still miss at the largest size are shown to the local vision-
        language model: if it cannot see the planted defect either, the region is untestable, not blind."""
        import cv2

        with self.lock:
            rng = np.random.default_rng(11)
            base = self.ref_images[0]
            fgs = self.gref.fg.reshape(-1, *self.gref.hw).cpu().numpy()
            m0 = self.part_mask(base, fgs[0])
            mh, mw = m0.shape
            tp = self.cal.policy.tau_pass
            ys_, xs_ = np.nonzero(m0)
            bx0, bx1 = xs_.min() / mw, (xs_.max() + 1) / mw  # the grid covers the part, not the photo
            by0, by1 = ys_.min() / mh, (ys_.max() + 1) / mh
            cx_of = lambda g: bx0 + (bx1 - bx0) * g / grid  # noqa: E731
            cy_of = lambda g: by0 + (by1 - by0) * g / grid  # noqa: E731
            cells = []
            for gy in range(grid):
                for gx in range(grid):
                    sub = m0[int(cy_of(gy) * mh):int(cy_of(gy + 1) * mh), int(cx_of(gx) * mw):int(cx_of(gx + 1) * mw)]
                    if sub.size and sub.mean() >= 0.5:  # the cell really is on the part
                        cells.append((gx, gy, cx_of(gx + 0.5), cy_of(gy + 0.5)))
            nref = len(self.ref_images)
            masks = {}
            jobs = []
            for gx, gy, cx, cy in cells:
                for k, sz in enumerate(sizes):
                    j = (gx + gy * grid + k) % nref
                    ref = self.ref_images[j]
                    rw, rh = ref.size
                    if j not in masks:
                        masks[j] = self.part_mask(ref, fgs[j] if j < len(fgs) else None)
                    rm = masks[j]
                    py = min(int(cy * rm.shape[0]), rm.shape[0] - 1)
                    px = min(int(cx * rm.shape[1]), rm.shape[1] - 1)
                    if not rm[py, px]:
                        continue  # this photo's part sits elsewhere: never plant on background
                    imd = imagine(ref, kind, sz * rw, rng, mask=rm, center=(cx * rw, cy * rh))
                    jobs.append((gx, gy, k, j, imd))
            caught: dict = {}
            largest_miss: dict = {}
            hw = self.mem.hw
            for i in range(0, len(jobs), 16):
                chunk = jobs[i:i + 16]
                _, dist, sc = self.mem.inspect([c[4].image for c in chunk], exclude_src=[c[3] for c in chunk])
                dmap = dist.reshape(-1, *hw).cpu().numpy()
                for (gx, gy, k, j, imd), s_, d in zip(chunk, sc.tolist(), dmap):
                    pm = cv2.resize(imd.mask.astype(np.float32), (hw[1], hw[0]), interpolation=cv2.INTER_AREA) > 0.01
                    pm = cv2.dilate(pm.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
                    located = bool(pm.any()) and float(d[pm].max()) >= 0.8 * float(d.max())
                    if s_ > tp and located:
                        if (gx, gy) not in caught or k < caught[(gx, gy)]:
                            caught[(gx, gy)] = k
                    elif k == len(sizes) - 1:
                        largest_miss[(gx, gy)] = imd
            # second opinion on the misses: is the planted defect even visible?
            invisible: set = set()
            vlm_checked = 0
            if verify and largest_miss:
                from . import vlm

                if vlm.available():
                    for key, imd in list(largest_miss.items())[:12]:
                        if key in caught:
                            continue
                        x, y = imd.center
                        r = max(24, int(imd.size_px * 0.8))
                        crop = imd.image.crop((int(x - r), int(y - r), int(x + r), int(y + r)))
                        try:
                            ans = vlm.generate([crop.resize((336, 336))],
                                               f"Is there a visible {kind} or line mark in this close-up of a part? Answer only yes or no.", 4)
                        except Exception:
                            break
                        vlm_checked += 1
                        if ans.strip().lower().startswith("no"):
                            invisible.add(key)
            out_cells = []
            state = {}
            for gx, gy, cx, cy in cells:
                k = caught.get((gx, gy))
                if k is not None:
                    st = "sharp" if k <= 1 else "medium" if k <= 3 else "large"
                else:
                    st = "untestable" if (gx, gy) in invisible else "blind"
                state[(gx, gy)] = st
                out_cells.append({"x": cx, "y": cy, "state": st, "minSizePct": round(100 * sizes[k], 1) if k is not None else None})
            # render: colour only the part's own pixels, cell by cell
            S = 384
            arr = np.asarray(base.convert("RGB").resize((S, S))).astype(np.float32) / 255
            msk = cv2.resize(m0.astype(np.uint8), (S, S), interpolation=cv2.INTER_NEAREST) > 0
            pal = {"sharp": (0.36, 0.78, 0.71), "medium": (0.95, 0.66, 0.23), "large": (0.94, 0.4, 0.35),
                   "blind": (0.94, 0.4, 0.35), "untestable": (0.56, 0.59, 0.76)}
            col = np.zeros_like(arr)
            alpha = np.zeros((S, S), np.float32)
            for (gx, gy), st in state.items():
                ys = slice(int(cy_of(gy) * S) + 1, int(cy_of(gy + 1) * S) - 1)  # 2 px gutter shows the grid
                xs = slice(int(cx_of(gx) * S) + 1, int(cx_of(gx + 1) * S) - 1)
                col[ys, xs] = pal[st]
                alpha[ys, xs] = 0.58 if st in ("blind", "large") else 0.48
            alpha *= msk
            img = arr * (1 - alpha[..., None]) + col * alpha[..., None]
            edges = cv2.Canny((msk * 255).astype(np.uint8), 50, 150) > 0
            img[edges] = (0.93, 0.91, 0.85)
            atlas = Image.fromarray((img * 255).astype(np.uint8))
            mins = [c["minSizePct"] for c in out_cells if c["minSizePct"] is not None]
            res = {"image": b64(atlas, S), "cells": out_cells, "cellSize": [float(bx1 - bx0) / grid, float(by1 - by0) / grid], "sizesPct": [round(100 * x, 1) for x in sizes],
                   "kind": kind, "regions": len(out_cells),
                   "blindCells": sum(c["state"] == "blind" for c in out_cells),
                   "untestableCells": sum(c["state"] == "untestable" for c in out_cells),
                   "sharpCells": sum(c["state"] == "sharp" for c in out_cells),
                   "medianMinSizePct": float(np.median(mins)) if mins else None, "tested": len(jobs),
                   "vlmChecked": vlm_checked,
                   "method": "leave-one-out scoring; must also localise the planted defect; misses double-checked by the local VLM"}
            self.emit("trust.blindspots", message="Mapped my blind spots", summary={k: v for k, v in res.items() if k != "image"})
            return res

    # ================================================================== GALAXY / SUMMARY
    def galaxy_payload(self) -> dict:
        refs = self.gref.cls.cpu().numpy()
        recs = [r for r in self.records if r.id in getattr(self, "_feat_cache", {})][-300:]
        parts = np.stack([self._feat_cache[r.id][2].cpu().numpy() for r in recs]) if recs else np.zeros((0, refs.shape[1]))
        return {"refs": refs, "parts": parts, "records": recs}

    def summary(self) -> dict:
        perf = self.performance() if self.records else {"n": 0}
        return {
            "id": self.id, "source": self.source, "name": self.name, "displayName": self.product.name,
            "plant": self.plant, "stage": self.stage,
            "created": self.created, "refs": len(getattr(self, "ref_images", [])),
            "policy": self.cal.policy.to_dict() if hasattr(self, "cal") else None,
            "conditions": self.conditions.__dict__, "shiftAlarm": bool(getattr(self, "guard", None) and self.guard.alarmed),
            "records": len(self.records), "questions": self.questions, "performance": perf,
            "budget": getattr(self, "budget", 0.10), "autopilot": getattr(self, "autopilot", True),
            "forecast": self.forecast, "hasTwin": self.twin is not None or self.relief, "relief": self.relief,
            "goldenUrl": getattr(self, "golden_url", None), "detectors": 2 if getattr(self, "golden", None) is not None and GOLDEN_GAIN > 0 else 1,
            "uploadsLeft": (len(self.eval_pool or self.spare_good) - self._upload_cursor)
            if self.product.source == "Upload" else None,
            "learnedDefects": [d["label"] for d in self.learned_defects],
            "hiveLibrary": [f["label"] for f in self.hive_library],
            "reviewers": self.reviewers,
        }


def _media_path(url: str):
    from .visual import MEDIA
    return MEDIA / url.replace("/media/", "", 1)


SESSIONS: dict[str, Session] = {}
