"""Save and restore product sessions, so a server restart loses nothing.

A session is pickled with torch.save. The heavy, rebuildable parts are swapped out first:
the DINOv2 model handle is dropped (re-attached on load), PIL images are stored as JPEG bytes,
and the lock is recreated.
"""
from __future__ import annotations

import copy
import io
import logging
import threading
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from .backbone import Backbone
from .data import DATA_ROOT

log = logging.getLogger("sandeha.persist")
STORE = DATA_ROOT / "sessions"
STORE.mkdir(parents=True, exist_ok=True)
_save_lock = threading.Lock()


def _to_jpeg(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.convert("RGB").save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _from_jpeg(b: bytes) -> Image.Image:
    return Image.open(io.BytesIO(b)).convert("RGB")


def snapshot(session) -> dict:
    d = dict(session.__dict__)
    d.pop("lock", None)
    d["bb"] = None
    d.pop("_pose_lib", None)  # rebuilt lazily
    if "mem" in d:
        mem = d["mem"]
        st = {k: v for k, v in mem.__dict__.items() if k != "bb"}
        if st.get("bank") is not None:
            st["bank"] = st["bank"].half()  # patch memories as fp16: half the size, same nearest neighbours
        d["mem_state"] = st
        d.pop("mem")
    if "gref" in d:  # reference patch features are only needed during genesis; keep embeddings + masks
        g = d["gref"]
        d["gref"] = type(g)(feats=g.feats[:, :0], cls=g.cls, hw=g.hw, fg=g.fg)
    if "ref_images" in d:
        d["ref_images"] = [_to_jpeg(im) for im in d["ref_images"]]
    if "_probe_imgs" in d:  # forgetting-check parts
        d["_probe_imgs"] = tuple([_to_jpeg(im) for im in lst] for lst in d["_probe_imgs"])
    if "imagined" in d:  # masks bit-packed
        d["imagined"] = [(x.kind, x.size_px, x.center, _to_jpeg(x.image), (np.packbits(x.mask.astype(bool)), x.mask.shape))
                         for x in d["imagined"]]
    d.pop("golden", None)  # rebuilt from the references on load
    if d.get("loo_maps") is not None:
        d["loo_maps"] = np.asarray(d["loo_maps"]).astype(np.float16)
    if d.get("twin") is not None:  # the voxel coordinate grid is rebuilt on load
        tw = copy.copy(d["twin"])
        tw.xyz = None
        d["twin"] = tw
    if "_feat_cache" in d:  # keep only the 384-number embeddings plus features of parts still awaiting review
        cache = {}
        for r in session.records:
            v = d["_feat_cache"].get(r.id)
            if v is None:
                continue
            pending = r.decision == "DOUBT" and r.review.get("final") not in ("GOOD", "DEFECT", "GHOST_CHECKED")
            cache[r.id] = v if pending and v[0] is not None else (None, None, v[2])
        d["_feat_cache"] = cache
    return d


def save(session) -> None:
    if session.stage in ("CREATED", "GENESIS"):
        return
    with _save_lock, session.lock:
        try:
            path = STORE / f"{session.id}.pt"
            tmp = path.with_suffix(".tmp")
            torch.save(snapshot(session), tmp)
            tmp.replace(path)
        except Exception:
            log.exception("could not save session %s", session.id)


def save_async(session) -> None:
    threading.Thread(target=save, args=(session,), daemon=True).start()


def load_all() -> dict:
    from .engine import Session
    from .imagine import Imagined
    from .memory import PatchMemory

    out = {}
    for f in sorted(STORE.glob("*.pt")):
        try:
            d = torch.load(f, map_location="cuda" if torch.cuda.is_available() else "cpu", weights_only=False)
            s = Session.__new__(Session)
            mem_state = d.pop("mem_state", None)
            s.__dict__.update(d)
            s.lock = threading.RLock()
            s.bb = Backbone.get("facebook/dinov2-small", 448)
            if mem_state is not None:
                m = PatchMemory.__new__(PatchMemory)
                m.__dict__.update(mem_state)
                m.bb = s.bb
                if m.bank is not None:  # stored as fp16; the live memory appends fp32 features
                    m.bank = m.bank.float().cuda() if torch.cuda.is_available() else m.bank.float()
                s.mem = m
            if isinstance(s.__dict__.get("ref_images"), list):
                s.ref_images = [_from_jpeg(b) for b in s.ref_images]
            s._board_building = False  # a save taken mid-build must not block rebuilding
            s._calibrating_board = False
            if isinstance(s.__dict__.get("_probe_imgs"), tuple):
                s._probe_imgs = tuple([_from_jpeg(b) for b in lst] for lst in s._probe_imgs)
            if isinstance(s.__dict__.get("imagined"), list):
                def _mask(m):
                    if isinstance(m, tuple):
                        bits, shape = m
                        return np.unpackbits(bits)[: int(np.prod(shape))].reshape(shape).astype(np.uint8)
                    return m
                s.imagined = [Imagined(image=_from_jpeg(img), mask=_mask(mask), kind=kind, size_px=size, center=c)
                              for kind, size, c, img, mask in s.imagined]
            if s.__dict__.get("loo_maps") is not None:
                s.loo_maps = np.asarray(s.loo_maps).astype(np.float32)
            tw = s.__dict__.get("twin")
            if tw is not None and getattr(tw, "xyz", None) is None:
                dev = tw.occ.device
                lin = torch.linspace(-tw.bound, tw.bound, tw.res, device=dev)
                zz, yy, xx = torch.meshgrid(lin, lin, lin, indexing="ij")
                tw.xyz = torch.stack([xx, yy, zz], -1).reshape(-1, 3)
            out[s.id] = s
            log.info("restored session %s (%s/%s, %d parts)", s.id, s.source, s.name, len(s.records))
        except Exception:
            log.exception("could not restore %s", f.name)
    return out


def forget(sid: str) -> None:
    (STORE / f"{sid}.pt").unlink(missing_ok=True)

