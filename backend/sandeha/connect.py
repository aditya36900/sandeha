"""Wiring map and connection check: which point is wired to which, and is every one of those wires intact?

Read from the good boards at full photo resolution (no Gerber or netlist file needed):

  * PADS        exposed metal: solder joints, IC pins, test pads, plated holes. Named by the part they belong to
                ("U1.3" = third pad of U1).
  * CONDUCTORS  copper under the solder mask is a lighter shade of the mask colour; the gaps between conductors
                are the darker shade. Every connected piece of copper, together with the pads soldered onto it, is
                one net. Two pads on the same net are wired together: that is the wiring map, point to point.
                Printed white ink that crosses a conductor is bridged (the copper carries on under it).

On each inspected board, in the golden-board frame:
  OPEN JOINT   a pad has lost its metal (no solder, lifted, joint gone)
  SHORT        metal joins pads of two different nets across a gap that is clear on every good board
  BROKEN WIRE  a mark on a conductor that no good board has. If it cuts right across, the pads on either side are
               no longer connected and both are named; otherwise it is reported as damage to that wire.

Every limit comes from good boards. Honest limits of one top-down photo: copper on the other side of the board,
vias and anything under a component body are invisible, and a joint that looks right but does not conduct cannot
be seen. scripts/connection_eval.py measures the catch and false-alarm rates with planted faults.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image

from .board import align, lab, to_work

VERSION = 2
K = 2             # the wiring map works at twice the component map's resolution (about the photo's own)
MIN_PAD = 60      # px at wiring resolution
BIG_PAD = 9000    # a connector shell, not a joint


def hi_align(img: Image.Image, bm) -> np.ndarray:
    """The photo warped into the golden-board frame at wiring resolution."""
    work = to_work(img)
    H, W = bm.golden.shape[:2]
    if work.shape[:2] != (H, W):
        a, _ = align(work, bm.golden)
        return cv2.resize(a, (K * W, K * H), interpolation=cv2.INTER_CUBIC)
    _, warp = align(work, bm.golden)
    big = np.asarray(img.convert("RGB").resize((K * W, K * H), Image.BICUBIC))
    w2 = warp.copy()
    w2[:, 2] *= K
    return cv2.warpAffine(big, w2, (K * W, K * H), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)


def _classes(rgb: np.ndarray):
    L = lab(rgb)
    chroma = np.linalg.norm(L[..., 1:] - 128, axis=2)
    ink = (L[..., 0] > 185) & (chroma < 9)
    metal = (L[..., 0] > 125) & (chroma < 22) & ~ink
    return L, ink, metal


def _lum(rgb: np.ndarray) -> np.ndarray:
    return cv2.GaussianBlur(lab(rgb)[..., 0], (0, 0), 1.5)


def _up(m: np.ndarray, shape) -> np.ndarray:
    return cv2.resize(m.astype(np.uint8), (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST).astype(bool)


@dataclass
class ConnMap:
    shape: tuple
    pad_lab: np.ndarray                        # int32, 0 = none
    net_lab: np.ndarray                        # int32, 0 = none (conductors incl. their pads)
    pads: list = field(default_factory=list)   # {id, comp, bbox, area, centroid, net, fracMed, fracLow}
    nets: list = field(default_factory=list)   # {id, pads, components, px, plane, links}
    board: np.ndarray | None = None
    wire: np.ndarray | None = None             # copper under the mask that can be judged (away from pads / ink / parts)
    mu: np.ndarray | None = None
    sd: np.ndarray | None = None
    med: float = 1.0
    two_tone: bool = True                      # copper visible through the mask?
    damage_max: int = 40
    joined_ok: set = field(default_factory=set)  # net pairs that metal joins on some good board
    boards: int = 0
    calib_cuts: int = 0
    version: int = VERSION

    # ------------------------------------------------------------------ build
    @classmethod
    def build(cls, bm, images: list[Image.Image], n_gold: int = 30) -> "ConnMap":
        aligned = [hi_align(im, bm) for im in images]
        g = np.median(np.stack(aligned[:n_gold]), 0).astype(np.uint8)
        shape = g.shape[:2]
        board = cv2.erode(_up(bm.board, shape).astype(np.uint8), np.ones((17, 17), np.uint8)).astype(bool)
        L, ink, metal = _classes(g)
        ink &= board
        metal &= board
        comp_any = np.zeros(shape, bool)
        comp_d = []
        for c in bm.components:
            m = _up(c.mask, shape)
            comp_any |= m
            comp_d.append((c.id, cv2.dilate(m.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)))
        other = cv2.dilate((ink | metal).astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
        dist = np.linalg.norm(L[..., 1:] - bm.mask_lab[1:], axis=2)
        mask_all = (dist < 26) & board & ~ink & ~metal
        mask_px = mask_all & ~other
        Lb = cv2.GaussianBlur(L[..., 0], (0, 0), 1.0)
        vals = Lb[mask_px]
        two = False
        copper = np.zeros(shape, bool)
        if vals.size > 2000:
            thr, _ = cv2.threshold(np.clip(vals, 0, 255).astype(np.uint8).reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            lo, hi = vals[vals <= thr], vals[vals > thr]
            two = bool(lo.size > 0.08 * vals.size and hi.size > 0.08 * vals.size and hi.mean() - lo.mean() > 10)
            if two:
                copper = mask_all & (Lb > thr)
                copper = cv2.morphologyEx(copper.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)).astype(bool)
        bare = mask_all & ~copper

        # ---- pads
        core = cv2.morphologyEx(metal.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        n, li, st, cent = cv2.connectedComponentsWithStats(core, 8)
        pad_lab = np.zeros(shape, np.int32)
        pads, per = [], {}
        for i in sorted(range(1, n), key=lambda i: (int(cent[i][1]) // 60, cent[i][0])):
            if st[i, 4] < MIN_PAD:
                continue
            m = li == i
            best, ov = None, 0
            for cid, dm in comp_d:
                o = int((m & dm).sum())
                if o > ov:
                    best, ov = cid, o
            comp = best if ov >= 0.3 * st[i, 4] else None
            k = len(pads) + 1
            if comp:
                per[comp] = per.get(comp, 0) + 1
            pad_lab[m] = k
            pads.append({"id": f"{comp}.{per[comp]}" if comp else f"TP{k}", "comp": comp, "bbox": [int(v) for v in st[i, :4]],
                         "area": int(st[i, 4]), "centroid": [float(cent[i][0]), float(cent[i][1])], "net": None})
        P = len(pads)

        # ---- conductors: copper + the pads on it; ink and the thin unclassified rims take the class next to them
        known = copper | bare | (pad_lab > 0)
        fill = cv2.dilate(ink.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & board & ~known
        # conductors are pieces of copper; pads never stitch two pieces together (a pad sits on exactly one)
        cond = copper.copy()
        if two and fill.any():
            _, idx = cv2.distanceTransformWithLabels((~known).astype(np.uint8), cv2.DIST_L2, 3, labelType=cv2.DIST_LABEL_PIXEL)
            ky, kx = np.nonzero(known)
            lut = np.zeros(idx.max() + 1, bool)
            lut[idx[ky, kx]] = copper[ky, kx]
            cond = cond | (fill & lut[idx])
        cond = cv2.morphologyEx(cond.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)).astype(bool)
        nn, ni, nst, _ = cv2.connectedComponentsWithStats(cond.astype(np.uint8), 4)
        net_lab = np.zeros(shape, np.int32)
        nets = []
        # each pad belongs to the copper piece that touches most of its rim
        of_pad = np.zeros(P + 1, int)
        for k in range(P):
            x, y, w, h = pads[k]["bbox"]
            y0, y1, x0, x1 = max(0, y - 7), min(shape[0], y + h + 7), max(0, x - 7), min(shape[1], x + w + 7)
            pm = (pad_lab[y0:y1, x0:x1] == k + 1).astype(np.uint8)
            rim = cv2.dilate(pm, np.ones((7, 7), np.uint8)).astype(bool) & ~pm.astype(bool)
            v = ni[y0:y1, x0:x1][rim]
            v = v[v > 0]
            if v.size >= max(8, 0.25 * rim.sum()):  # copper along at least a quarter of the pad's edge
                cnt = np.bincount(v)
                of_pad[k + 1] = int(cnt.argmax())
        for i in range(1, nn):
            on = [k for k in range(P) if of_pad[k + 1] == i]
            if nst[i, 4] < 150 or not on:
                continue
            nid = f"N{len(nets) + 1}"
            net_lab[ni == i] = len(nets) + 1
            for k in on:
                pads[k]["net"] = nid
                net_lab[pad_lab == k + 1] = len(nets) + 1
            pts = np.array([pads[k]["centroid"] for k in on])
            links = []
            if len(on) > 1:  # point-to-point links: a minimum spanning tree over the pads of this conductor
                d = np.linalg.norm(pts[:, None] - pts[None], axis=2)
                inn = [0]
                while len(inn) < len(on):
                    sub = d[np.ix_(inn, [j for j in range(len(on)) if j not in inn])]
                    out_idx = [j for j in range(len(on)) if j not in inn]
                    a, b = np.unravel_index(int(sub.argmin()), sub.shape)
                    links.append([pads[on[inn[a]]]["id"], pads[on[out_idx[b]]]["id"]])
                    inn.append(out_idx[b])
            nets.append({"id": nid, "pads": [pads[k]["id"] for k in on],
                         "components": sorted({pads[k]["comp"] for k in on if pads[k]["comp"]}),
                         "px": int(nst[i, 4]), "plane": len(on) > 12, "links": links})

        cm = cls(shape=shape, pad_lab=pad_lab, net_lab=net_lab, pads=pads, nets=nets, board=board, two_tone=two, boards=len(aligned))
        cm.golden = g
        busy = cv2.dilate(((pad_lab > 0) | ink | comp_any).astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
        cm.wire = copper & (net_lab > 0) & ~busy if two else np.zeros(shape, bool)
        gl = _lum(g)
        cm.med = float(np.median(gl[board]))
        lums = [_lum(a) / cm._scale(a) for a in aligned]
        cm.mu = np.mean(lums, 0).astype(np.float32)
        cm.sd = np.std(lums, 0).astype(np.float32)
        del lums
        feats = [cm._features(a) for a in aligned]
        fr = np.array([f["frac"] for f in feats])
        for k in range(P):
            med = float(np.median(fr[:, k]))
            rsd = 1.4826 * float(np.median(np.abs(fr[:, k] - med))) + 0.02
            pads[k]["fracMed"] = round(med, 3)
            pads[k]["fracLow"] = round(float(max(0.0, min(med - 6 * rsd, fr[:, k].min() - 0.15, 0.6 * med))), 3)
        dmg = np.array([f["damage"] for f in feats], np.float32)
        cm.damage_max = int(max(60, 1.5 * np.quantile(dmg, 0.97) + 20))
        cm.calib_cuts = int(sum(bool(f["cuts"]) for f in feats))
        for f in feats:
            cm.joined_ok |= f["joined"]
        return cm

    def _pad_zone(self) -> np.ndarray:
        z = getattr(self, "_pz", None)
        if z is None:
            z = self._pz = cv2.dilate((self.pad_lab > 0).astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
        return z

    def _scale(self, a: np.ndarray) -> float:
        return float(np.clip(np.median(_lum(a)[self.board]) / self.med, 0.8, 1.25)) if self.med else 1.0

    # ------------------------------------------------------------------ measure one aligned board
    def _features(self, a: np.ndarray) -> dict:
        al = _lum(a)
        scale = float(np.clip(np.median(al[self.board]) / self.med, 0.8, 1.25))
        _, ink, metal = _classes(a)
        m = cv2.morphologyEx((metal & self.board).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)).astype(bool)
        P = len(self.pads)
        area = np.array([p["area"] for p in self.pads], np.float32)
        La = lab(a)
        solderish = (La[..., 0] > 95 * scale) & (np.linalg.norm(La[..., 1:] - 128, axis=2) < 27)
        frac = np.bincount(self.pad_lab[solderish], minlength=P + 1)[1:] / np.maximum(area, 1)
        # shorts: one blob of metal sitting on pads of two different nets
        nm, ci = cv2.connectedComponents(m.astype(np.uint8), 8)
        tab = np.zeros((P + 1, nm), np.int64)
        np.add.at(tab, (self.pad_lab[m], ci[m]), 1)
        joined, where = set(), {}
        new_px = np.bincount(ci[m & ~self._pad_zone()], minlength=nm)
        strong = tab[1:] >= np.maximum(12, 0.2 * area)[:, None]
        for b in np.nonzero(strong.sum(0) >= 2)[0]:
            ks = [int(k) for k in np.nonzero(strong[:, b])[0]]
            for i in range(len(ks)):
                for j in range(i + 1, len(ks)):
                    A_, B_ = self.pads[ks[i]], self.pads[ks[j]]
                    if abs(A_["centroid"][0] - B_["centroid"][0]) + abs(A_["centroid"][1] - B_["centroid"][1]) > 260:
                        continue
                    if new_px[b] < 45:  # the pads merely look merged (blur, glare): no new metal between them
                        continue
                    joined.add((ks[i], ks[j]))
                    where[(ks[i], ks[j])] = int(b)
        # wires: the largest mark on a conductor that is unlike every good board
        z = np.abs(al / scale - self.mu) / (self.sd + 5.0)
        dev = cv2.morphologyEx(((z > 5.0) & self.wire).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        n, li, st, _ = cv2.connectedComponentsWithStats(dev, 8)
        damage, blob, cuts = 0, None, []
        if n > 1:
            order = 1 + np.argsort(-st[1:, 4])
            i = int(order[0])
            damage, blob = int(st[i, 4]), (li == i, [int(v) for v in st[i, :4]])
            for i in order[:6]:
                if st[i, 4] < 28:
                    break
                bm_ = li == int(i)
                cut = self._severs(bm_, [int(v) for v in st[i, :4]])
                if cut:
                    cuts.append((bm_, [int(v) for v in st[i, :4]], int(st[i, 4]), cut))
        return {"frac": frac, "joined": joined, "where": where, "blobs": ci, "damage": damage, "blob": blob, "cuts": cuts}

    def _severs(self, bm_: np.ndarray, box: list) -> dict | None:
        """Does this mark cut its conductor in two, with pads left on both sides?"""
        k = int(np.bincount(self.net_lab[bm_]).argmax())
        if k <= 0:
            return None
        nt = self.nets[k - 1]
        if len(nt["pads"]) < 2:
            return None
        x, y, w, h = box
        pad = 90  # look only around the mark: a cut is a local event
        y0, y1, x0, x1 = max(0, y - pad), min(self.shape[0], y + h + pad), max(0, x - pad), min(self.shape[1], x + w + pad)
        before = (self.net_lab[y0:y1, x0:x1] == k)
        after = before & ~cv2.dilate(bm_[y0:y1, x0:x1].astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
        nb, _ = cv2.connectedComponents(before.astype(np.uint8), 4)
        na, parts = cv2.connectedComponents(after.astype(np.uint8), 4)
        big = [j for j in range(1, na) if (parts == j).sum() >= 60]
        if len(big) <= max(1, nb - 1):   # the conductor was already in pieces inside this window, or stays whole
            return None
        # the cut is real only if the pieces cannot rejoin elsewhere on the board
        whole = (self.net_lab == k) & ~cv2.dilate(bm_.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
        _, wp = cv2.connectedComponents(whole.astype(np.uint8), 4)
        by_id = {p["id"]: p for p in self.pads}
        side = {}
        for pid in nt["pads"]:
            px, py, pw, ph = by_id[pid]["bbox"]
            v = wp[py:py + ph, px:px + pw]
            v = v[v > 0]
            if v.size:
                side.setdefault(int(np.bincount(v).argmax()), []).append(pid)
        groups = sorted(side.values(), key=len)
        if len(groups) < 2:
            return None
        return {"net": nt["id"], "isolated": groups[0][:6], "from": [q for grp in groups[1:] for q in grp][:6]}

    # ------------------------------------------------------------------ check a board
    def check(self, a: np.ndarray, skip_components: set | None = None) -> dict:
        """a: the board at wiring resolution in the golden frame (see hi_align)."""
        f = self._features(a)
        H, W = self.shape
        skip = skip_components or set()
        opens, shorts, traces = [], [], []
        by_id = {p["id"]: p for p in self.pads}
        for k, p in enumerate(self.pads):
            if p.get("fracMed", 0) < 0.5 or p["area"] > BIG_PAD:
                continue
            fr = float(f["frac"][k])
            if fr < p["fracLow"]:
                x, y, w, h = p["bbox"]
                opens.append({"pad": p["id"], "component": p["comp"], "net": p["net"], "bbox": [x / W, y / H, w / W, h / H],
                              "sameAs": p["comp"] if p["comp"] in skip else None,
                              "why": f"only {round(100 * fr)}% of this joint's metal is there (good boards: {round(100 * p['fracMed'])}%, never under {round(100 * p['fracLow'])}%)"})
        for key in sorted(f["joined"] - self.joined_ok):
            b = f["where"][key]
            A, B = self.pads[key[0]], self.pads[key[1]]
            ys, xs = np.nonzero((f["blobs"] == b) & (self.pad_lab == 0))
            if not len(xs):
                continue
            x0, y0 = int(min(A["bbox"][0], B["bbox"][0])), int(min(A["bbox"][1], B["bbox"][1]))
            x1 = int(max(A["bbox"][0] + A["bbox"][2], B["bbox"][0] + B["bbox"][2]))
            y1 = int(max(A["bbox"][1] + A["bbox"][3], B["bbox"][1] + B["bbox"][3]))
            same = A["net"] is not None and A["net"] == B["net"]
            shorts.append({"a": A["id"], "b": B["id"], "nets": [A["net"], B["net"]], "sameNet": same,
                           "components": sorted({c for c in (A["comp"], B["comp"]) if c}),
                           "bbox": [x0 / W, y0 / H, (x1 - x0) / W, (y1 - y0) / H],
                           "why": f"metal joins {A['id']} to {B['id']}; these two were never joined on the {self.boards} good boards"
                                  + (" (same conductor on the map: excess solder rather than a short)" if same else "")})
        cut_boxes = []
        for bm_, (x, y, w, h), px, cut in f["cuts"]:
            cut_boxes.append((x, y, w, h))
            nt = next(n for n in self.nets if n["id"] == cut["net"])
            traces.append({"net": cut["net"], "components": nt["components"], "bbox": [x / W, y / H, w / W, h / H], "px": px, "cut": cut,
                           "why": f"the wire is cut: {', '.join(cut['isolated'])} no longer reaches {', '.join(cut['from'])} "
                                  f"(a {px} px mark right across conductor {cut['net']})"})
        if f["damage"] > self.damage_max and f["blob"] is not None and tuple(f["blob"][1]) not in cut_boxes:
            bm_, (x, y, w, h) = f["blob"]
            k = int(np.bincount(self.net_lab[bm_]).argmax())
            nt = self.nets[k - 1] if k > 0 else None
            traces.append({"net": nt["id"] if nt else None, "components": nt["components"] if nt else [],
                           "bbox": [x / W, y / H, w / W, h / H], "px": f["damage"], "cut": None,
                           "why": f"a {f['damage']} px mark on conductor {nt['id'] if nt else '?'} that no good board has "
                                  f"(good boards stay under {self.damage_max} px); it does not cut right across, so the wire may still conduct"})
        real_opens = [o for o in opens if not o["sameAs"]]
        shorts = shorts[:6]
        return {"pads": len([p for p in self.pads if p.get("fracMed", 0) >= 0.5 and p["area"] <= BIG_PAD]),
                "nets": len(self.nets), "links": sum(len(n["links"]) for n in self.nets),
                "opens": opens, "shorts": shorts, "traces": traces,
                "faults": len(real_opens) + len(shorts) + len(traces), "ok": not (real_opens or shorts or traces)}

    # ------------------------------------------------------------------ pictures
    def _crop(self, out: np.ndarray) -> np.ndarray:
        ys, xs = np.nonzero(self.board)
        return out[max(0, ys.min() - 16):ys.max() + 16, max(0, xs.min() - 16):xs.max() + 16]

    def crop_box(self) -> list:
        ys, xs = np.nonzero(self.board)
        return [max(0, int(xs.min()) - 16), max(0, int(ys.min()) - 16), int(xs.max()) + 16, int(ys.max()) + 16]

    def colours(self) -> list:
        rng = np.random.default_rng(11)
        cols = []
        for j in range(len(self.nets)):
            h = (j * 0.61803398875 + 0.07) % 1.0
            rgb = cv2.cvtColor(np.uint8([[[int(179 * h), 190, 255]]]), cv2.COLOR_HSV2RGB)[0, 0]
            cols.append([int(v) for v in rgb])
        return cols

    def wiring_image(self, base: np.ndarray | None = None, res: dict | None = None) -> Image.Image:
        """The wiring map: every conductor in its own colour over a dimmed board, pads outlined. With `res`, the
        findings of one board are drawn on top (red = open joint / short / cut, amber = damage)."""
        g = self.golden if base is None else base
        out = (g.astype(np.float32) * 0.28)
        cols = self.colours()
        for j, col in enumerate(cols):
            m = self.net_lab == j + 1
            out[m] = 0.25 * out[m] + 0.75 * np.array(col, np.float32)
        out = out.astype(np.uint8)
        H, W = self.shape
        bad = {o["pad"] for o in (res or {}).get("opens", [])}
        for p in self.pads:
            x, y, w, h = p["bbox"]
            if p["id"] in bad:
                cv2.rectangle(out, (x - 3, y - 3), (x + w + 2, y + h + 2), (255, 40, 40), 3)
            else:
                cv2.rectangle(out, (x - 1, y - 1), (x + w, y + h), (255, 255, 255), 1)
        for s in (res or {}).get("shorts", []):
            x, y, w, h = s["bbox"]
            cv2.rectangle(out, (int(x * W) - 5, int(y * H) - 5), (int((x + w) * W) + 5, int((y + h) * H) + 5), (255, 40, 40), 3)
        for t in (res or {}).get("traces", []):
            x, y, w, h = t["bbox"]
            cv2.rectangle(out, (int(x * W) - 6, int(y * H) - 6), (int((x + w) * W) + 6, int((y + h) * H) + 6),
                          (255, 40, 40) if t.get("cut") else (255, 180, 0), 3)
        return Image.fromarray(self._crop(out))

    def public(self) -> dict:
        x0, y0, x1, y1 = self.crop_box()
        w, h = x1 - x0, y1 - y0
        cols = self.colours()
        by = {p["id"]: p for p in self.pads}
        nets = []
        for j, n in enumerate(self.nets):
            nets.append({**n, "colour": "#%02x%02x%02x" % tuple(cols[j]),
                         "points": {pid: [(by[pid]["centroid"][0] - x0) / w, (by[pid]["centroid"][1] - y0) / h] for pid in n["pads"]}})
        return {"twoTone": self.two_tone, "pads": len(self.pads), "nets": nets,
                "links": sum(len(n["links"]) for n in self.nets),
                "padList": [{"id": p["id"], "component": p["comp"], "net": p["net"],
                             "at": [(p["centroid"][0] - x0) / w, (p["centroid"][1] - y0) / h]} for p in self.pads],
                "learnedFrom": self.boards, "aspect": w / h,
                "note": ("Read from one top-down photo at full resolution. Copper on the other side of the board, vias and "
                         "anything under a part are invisible, so two conductors shown as separate here may be joined "
                         "elsewhere; a joint that looks right but does not conduct cannot be seen."
                         + ("" if self.two_tone else " On this board the copper does not show through the coating, so only pads are mapped."))}


# ---------------------------------------------------------------------- planted connection faults (known truth)
def plant(img: Image.Image, bm, cm: ConnMap, kind: str, rng):
    """Plant one connection fault on a good board. Returns (board at wiring resolution, truth) or None.
    kind: 'short' (solder bridge between two conductors) | 'open' (a joint with no solder) | 'cut' (a wire cut across)."""
    a = hi_align(img, bm).copy()
    H, W = cm.shape
    truth = {"kind": kind}
    by = {p["id"]: p for p in cm.pads}
    if kind == "short":
        cands = []
        ok = [k for k, p in enumerate(cm.pads) if p["area"] <= BIG_PAD and p.get("fracMed", 0) >= 0.8 and p["area"] >= 150]
        for i in range(len(ok)):
            for j in range(i + 1, len(ok)):
                A_, B_ = cm.pads[ok[i]], cm.pads[ok[j]]
                d = float(np.hypot(A_["centroid"][0] - B_["centroid"][0], A_["centroid"][1] - B_["centroid"][1]))
                if d < 90 and (ok[i], ok[j]) not in cm.joined_ok and A_["comp"] != B_["comp"]:
                    cands.append((A_, B_))
        if not cands:
            return None
        A, B = cands[int(rng.integers(len(cands)))]
        col = np.median(a[cm.pad_lab == cm.pads.index(A) + 1], axis=0)
        blob = np.zeros(cm.shape, np.uint8)
        cv2.line(blob, tuple(int(v) for v in A["centroid"]), tuple(int(v) for v in B["centroid"]), 1, int(rng.integers(7, 12)))
        soft = cv2.GaussianBlur(blob.astype(np.float32), (0, 0), 1.2)[..., None]
        a = (a * (1 - soft) + (col * rng.uniform(0.92, 1.05)) * soft).clip(0, 255).astype(np.uint8)
        truth.update(a=A["id"], b=B["id"])
    elif kind == "open":
        cands = [k for k, p in enumerate(cm.pads) if p.get("fracMed", 0) >= 0.8 and 100 <= p["area"] <= 4000 and p["comp"]]
        if not cands:
            return None
        k = cands[int(rng.integers(len(cands)))]
        m = cv2.dilate((cm.pad_lab == k + 1).astype(np.uint8), np.ones((5, 5), np.uint8)).astype(np.float32)
        soft = cv2.GaussianBlur(m, (0, 0), 1.5)[..., None]
        ring = cv2.dilate(m.astype(np.uint8), np.ones((25, 25), np.uint8)).astype(bool) & cm.wire
        col = np.median(a[ring], axis=0) if ring.sum() > 20 else np.median(a[cm.wire], axis=0)
        a = (a * (1 - soft) + (col * rng.uniform(0.85, 1.0)) * soft).clip(0, 255).astype(np.uint8)
        truth.update(pad=cm.pads[k]["id"])
    else:
        # cut a wire: a narrow place on a conductor that has pads on both sides
        cands = [j for j, n in enumerate(cm.nets) if 2 <= len(n["pads"]) and not n["plane"]]
        rng.shuffle(cands)
        for j in cands:
            reg = ((cm.net_lab == j + 1) & cm.wire).astype(np.uint8)
            dt = cv2.distanceTransform(reg, cv2.DIST_L2, 3)
            ys, xs = np.nonzero((dt > 2) & (dt < 14))
            if not len(xs):
                continue
            for _ in range(25):
                i = int(rng.integers(len(xs)))
                x, y = int(xs[i]), int(ys[i])
                for ang in (0.0, np.pi / 2, np.pi / 4, 3 * np.pi / 4):
                    ln = 46
                    p0 = (int(x - ln * np.cos(ang)), int(y - ln * np.sin(ang)))
                    p1 = (int(x + ln * np.cos(ang)), int(y + ln * np.sin(ang)))
                    blob = np.zeros(cm.shape, np.uint8)
                    cv2.line(blob, p0, p1, 1, 6)
                    blob &= (cm.wire & (cm.net_lab == j + 1)).astype(np.uint8)
                    rest = (cm.net_lab == j + 1) & ~cv2.dilate(blob, np.ones((3, 3), np.uint8)).astype(bool)
                    _, parts = cv2.connectedComponents(rest.astype(np.uint8), 4)
                    sides = set()
                    for pid in cm.nets[j]["pads"]:
                        px, py, pw, ph = by[pid]["bbox"]
                        v = parts[py:py + ph, px:px + pw]
                        v = v[v > 0]
                        if v.size:
                            sides.add(int(np.bincount(v).argmax()))
                    if len(sides) > 1 and blob.sum() > 30:
                        soft = cv2.GaussianBlur(blob.astype(np.float32), (0, 0), 0.8)[..., None]
                        col = np.array([205, 150, 110]) if rng.random() < 0.5 else np.array([28, 26, 30])  # bared laminate / burn
                        a = (a * (1 - soft) + col * soft).clip(0, 255).astype(np.uint8)
                        truth.update(net=cm.nets[j]["id"], at=[x, y])
                        return a, truth
        return None
    return a, truth
