"""Component-level inspection for electronics: every part on the board gets its own verdict.

Built from the same ~30 good boards the anomaly memory uses, with no labels:
  1. align every good board to the first one (ECC, rotation + translation) and take the pixel-wise median
     = the "golden board",
  2. find the solder-mask colour (largest Lab cluster on the board) and segment everything that is NOT solder
     mask and is thick enough to not be silkscreen text -> components (bodies merged with their pads),
  3. name each component with a classifier trained on 1,141 photographed SMD parts (MIT data, 86.7% on its
     holdout), plus geometry for connectors, holes and large metal parts it was never taught,
  4. learn each component's own normal variation leave-one-out over the good boards: how far it moves,
     how well it matches the golden board, its colour, its anomaly heat, its terminal heat,
  5. on a new board: align, then for each component measure the same things and diagnose
       MISSING      body gone (match collapses, the spot now looks like bare solder mask)
       ROTATED      the golden part matches better turned 90/180 degrees (orientation / polarity)
       SHIFTED      matches well but displaced beyond anything seen on good boards (wrong place)
       BURNT        darkened / discoloured beyond the good boards
       SOLDER       anomaly concentrated at the terminals (joint, bridge, excess or missing solder)
       WRONG_PART   does not match the golden part, but something is there
       DAMAGED      unusual (patch memory) without one of the patterns above
     and EXTRA for unusual regions where the golden board has no component (debris, solder balls, extra parts).
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

WORK_W = 768
CLF_FILE = Path(__file__).resolve().parents[2] / "data" / "results" / "component_clf.pkl"
STATUS_TEXT = {
    "OK": "as on good boards",
    "MISSING": "component missing",
    "ROTATED": "rotated / reversed (orientation or polarity)",
    "SHIFTED": "moved off its position",
    "BURNT": "burnt or discoloured",
    "SOLDER": "solder joint suspect",
    "WRONG_PART": "does not match the expected part",
    "DAMAGED": "damaged or unusual surface",
    "EXTRA": "contamination or extra material (dirt, flux or moisture residue, solder balls, debris)",
}
PREFIX = {"resistor": "R", "capacitor": "C", "diode / LED": "D", "inductor": "L", "transistor": "Q", "IC": "U",
          "connector": "J", "hole / pad": "H", "metal part": "M", "other": "X"}


# ------------------------------------------------------------------ geometry helpers
def _gray(a: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)


def to_work(img: Image.Image) -> np.ndarray:
    w, h = img.size
    s = WORK_W / w
    return np.asarray(img.convert("RGB").resize((WORK_W, max(8, int(round(h * s)))), Image.BILINEAR))


def align(a: np.ndarray, ref: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Warp `a` onto `ref` (Euclidean). Returns (aligned image, 2x3 warp mapping ref coords -> a coords)."""
    if a.shape[:2] != ref.shape[:2]:  # a photo with other proportions (e.g. a square thumbnail): bring it to the frame
        a = cv2.resize(a, (ref.shape[1], ref.shape[0]), interpolation=cv2.INTER_LINEAR)
    ga = cv2.GaussianBlur(_gray(a), (5, 5), 0).astype(np.float32) / 255
    gr = cv2.GaussianBlur(_gray(ref), (5, 5), 0).astype(np.float32) / 255
    warp = np.eye(2, 3, dtype=np.float32)
    try:
        f = 0.25  # coarse-to-fine: solve small, then refine at full working size
        small_a = cv2.resize(ga, None, fx=f, fy=f)
        small_r = cv2.resize(gr, None, fx=f, fy=f)
        (sx, sy), _ = cv2.phaseCorrelate(small_r, small_a)
        warp[0, 2], warp[1, 2] = sx, sy
        crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 60, 1e-5)
        _, warp = cv2.findTransformECC(small_r, small_a, warp, cv2.MOTION_EUCLIDEAN, crit, None, 5)
        warp[:, 2] /= f
        _, warp = cv2.findTransformECC(gr, ga, warp, cv2.MOTION_EUCLIDEAN, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 1e-5), None, 5)
    except cv2.error:
        (sx, sy), _ = cv2.phaseCorrelate(gr, ga)
        warp = np.array([[1, 0, sx], [0, 1, sy]], np.float32)
    h, w = ref.shape[:2]
    out = cv2.warpAffine(a, warp, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)
    return out, warp


def warp_map(m: np.ndarray, src_shape, warp: np.ndarray, ref_shape) -> np.ndarray:
    """Bring a map defined on the source image (any size) into the aligned reference frame."""
    h, w = src_shape[:2]
    mm = cv2.resize(m.astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
    H, W = ref_shape[:2]
    return cv2.warpAffine(mm, warp, (W, H), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_CONSTANT)


def board_mask(a: np.ndarray) -> np.ndarray:
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]]).astype(np.int16)
    bg = np.median(border, axis=0)
    m = (np.abs(a.astype(np.int16) - bg).sum(-1) > 60).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = np.zeros_like(m)
    if cs:
        cv2.drawContours(out, [max(cs, key=cv2.contourArea)], -1, 1, cv2.FILLED)
    return out.astype(bool)


def lab(a: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(a, cv2.COLOR_RGB2LAB).astype(np.float32)


def _extra_why(a: np.ndarray, reg: np.ndarray, bm) -> str:
    La, Lg = lab(a)[reg], lab(bm.golden)[reg]
    dl = float(La[:, 0].mean() - Lg[:, 0].mean())
    dab = float(np.linalg.norm(La[:, 1:].mean(0) - Lg[:, 1:].mean(0)))
    metal = float(((La[:, 0] > 150) & (np.linalg.norm(La[:, 1:] - 128, axis=1) < 25)).mean())
    if metal > 0.35 and dl > 8:
        look = "bright metallic: a solder ball or splash"
    elif dl < -10:
        look = "darker than the bare board: dirt, residue or a stain"
    elif dab > 8:
        look = "discoloured: flux or moisture residue, or a stain"
    else:
        look = "texture change on bare board: debris or residue"
    return f"{look} (lightness {dl:+.0f}, colour shift {dab:.0f}) where the golden board has no component"


def _dark_centre(golden: np.ndarray, x: int, y: int, w: int, h: int) -> bool:
    cy, cx = y + h // 2, x + w // 2
    r = max(1, min(w, h) // 6)
    c = golden[cy - r:cy + r + 1, cx - r:cx + r + 1].astype(np.float32).mean()
    ring = golden[y:y + h, x:x + w].astype(np.float32).mean()
    return abs(w - h) < 0.35 * max(w, h) and c < 0.55 * ring


# ------------------------------------------------------------------ synthetic component faults (known truth)
FAULTS = ("missing", "shifted", "rotated", "burnt", "solder_bridge", "solder_dry")
EXPECT = {"missing": {"MISSING"}, "shifted": {"SHIFTED", "WRONG_PART"}, "rotated": {"ROTATED", "WRONG_PART"},
          "burnt": {"BURNT"}, "solder_bridge": {"SOLDER", "DAMAGED", "WRONG_PART"}, "solder_dry": {"SOLDER", "DAMAGED"}}


def plant_fault(img: Image.Image, bm: "BoardMap", comp_id: str, kind: str, rng: np.random.Generator) -> Image.Image:
    """Make the named component faulty on a real board photo. Works in the photo's own frame: the
    component's golden-board footprint is carried over through the board alignment."""
    c = next(x for x in bm.components if x.id == comp_id)
    work = to_work(img)
    _, warp = align(work, bm.golden)
    H, W = work.shape[:2]
    m = cv2.warpAffine(c.mask.astype(np.uint8), warp, (W, H), flags=cv2.INTER_NEAREST)  # golden -> this photo
    m = cv2.dilate(m, np.ones((3, 3), np.uint8))
    a = work.copy()
    ys, xs = np.nonzero(m)
    if not len(xs):
        return img
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    w, h = x1 - x0 + 1, y1 - y0 + 1
    bgr = lambda im: cv2.cvtColor(im, cv2.COLOR_RGB2BGR)  # noqa: E731
    rgb = lambda im: cv2.cvtColor(im, cv2.COLOR_BGR2RGB)  # noqa: E731
    if kind == "missing":
        a = rgb(cv2.inpaint(bgr(a), cv2.dilate(m, np.ones((5, 5), np.uint8)), 7, cv2.INPAINT_TELEA))
    elif kind in ("shifted", "rotated"):
        patch = a[y0:y1 + 1, x0:x1 + 1].copy()
        pm = m[y0:y1 + 1, x0:x1 + 1].astype(bool)
        a = rgb(cv2.inpaint(bgr(a), cv2.dilate(m, np.ones((5, 5), np.uint8)), 7, cv2.INPAINT_TELEA))
        if kind == "rotated":
            k = 2 if abs(w - h) > 0.2 * max(w, h) else int(rng.choice([1, 2, 3]))  # reversed, or turned in place
            patch, pm = np.rot90(patch, k), np.rot90(pm, k)
            dx, dy = (w - patch.shape[1]) // 2, (h - patch.shape[0]) // 2
        else:
            ang = rng.uniform(0, 2 * np.pi)
            step = max(6, int(0.45 * max(w, h)))
            dx, dy = int(step * np.cos(ang)), int(step * np.sin(ang))
        ty, tx = y0 + dy, x0 + dx
        ph, pw = patch.shape[:2]
        if 0 <= ty and 0 <= tx and ty + ph <= H and tx + pw <= W:
            region = a[ty:ty + ph, tx:tx + pw]
            region[pm] = patch[pm]
    elif kind == "burnt":
        body = m.astype(bool)
        L = cv2.cvtColor(a, cv2.COLOR_RGB2LAB).astype(np.float32)
        L[body, 0] *= rng.uniform(0.35, 0.5)
        L[body, 1] += 6
        L[body, 2] += 14
        a = cv2.cvtColor(np.clip(L, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)
        halo = cv2.GaussianBlur(cv2.dilate(m, np.ones((9, 9), np.uint8)).astype(np.float32), (21, 21), 0)[..., None]
        a = (a * (1 - 0.35 * halo)).astype(np.uint8)  # soot around it
    else:  # solder at one terminal
        horiz = w >= h
        end = int(rng.integers(2))
        if horiz:
            cx, cy = (x0 if end == 0 else x1), (y0 + y1) // 2
            ax_, ay_ = max(4, int(0.25 * w)), max(3, int(0.45 * h))
        else:
            cx, cy = (x0 + x1) // 2, (y0 if end == 0 else y1)
            ax_, ay_ = max(3, int(0.45 * w)), max(4, int(0.25 * h))
        blob = np.zeros((H, W), np.uint8)
        if kind == "solder_bridge":  # a bright tin blob spilling off the joint
            cv2.ellipse(blob, (int(cx), int(cy)), (int(ax_ * 1.3), int(ay_ * 1.3)), 0, 0, 360, 1, -1)
            col = np.array([205, 205, 200], np.float32)
            g = cv2.GaussianBlur(blob.astype(np.float32), (5, 5), 0)[..., None]
            shine = rng.normal(0, 12, a.shape).astype(np.float32)
            a = np.clip(a * (1 - g) + (col + shine) * g, 0, 255).astype(np.uint8)
        else:  # dry / insufficient joint: the shiny tin turns dull grey-black
            cv2.ellipse(blob, (int(cx), int(cy)), (ax_, ay_), 0, 0, 360, 1, -1)
            sel = (blob > 0) & m.astype(bool)
            a[sel] = (a[sel].astype(np.float32) * 0.45 + np.array([40, 38, 36]) * 0.55).astype(np.uint8)
    return Image.fromarray(a).resize(img.size, Image.BILINEAR)


def _split_merged(comp: np.ndarray, golden: np.ndarray, big_area: float) -> np.ndarray:
    """Parts joined by a trace or an outline form one blob. Split big blobs at their narrow necks
    (watershed on the distance transform): each thick core becomes its own component."""
    # printed markings on bodies (IC part numbers, resistor codes) leave holes: fill each blob first
    cs, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(comp)
    cv2.drawContours(filled, cs, -1, 1, cv2.FILLED)
    n, lab_img, st, _ = cv2.connectedComponentsWithStats(filled, 8)
    out = filled.copy()
    for i in range(1, n):
        area = st[i, cv2.CC_STAT_AREA]
        if area < big_area:
            continue
        m = (lab_img == i).astype(np.uint8)
        d = cv2.distanceTransform(m, cv2.DIST_L2, 5)
        # local thickness peaks; two peaks belong to one part unless a narrow neck separates them
        peak = (d >= cv2.dilate(d, np.ones((9, 9), np.uint8))) & (d >= 5)
        ys, xs = np.nonzero(peak)
        order = np.argsort(-d[ys, xs])
        kept: list[tuple[int, int, float]] = []
        for j in order:
            y, x, v = int(ys[j]), int(xs[j]), float(d[ys[j], xs[j]])
            same = False
            for ky, kx, kv in kept:
                t = np.linspace(0, 1, 24)
                line = d[(ky + t * (y - ky)).astype(int), (kx + t * (x - kx)).astype(int)]
                if line.min() >= 0.55 * min(v, kv):  # no neck in between
                    same = True
                    break
            if not same:
                kept.append((y, x, v))
        if len(kept) < 2:  # one part, however large (connector, IC)
            continue
        markers = np.ones(m.shape, np.int32)  # 1 = outside this blob
        markers[m == 1] = 0  # unknown: to be flooded
        for t_, (y, x, v) in enumerate(kept):
            cv2.circle(markers, (x, y), max(2, int(0.5 * v)), t_ + 2, -1)
        ws = cv2.watershed(cv2.cvtColor(golden, cv2.COLOR_RGB2BGR), markers)
        out[(m == 1) & (ws <= 1)] = 0  # cut along the watershed lines between cores
    return cv2.morphologyEx(out, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))


# ------------------------------------------------------------------ component typing
_CLF = None


def _classifier():
    global _CLF
    if _CLF is None:
        if CLF_FILE.exists():
            with open(CLF_FILE, "rb") as f:
                _CLF = pickle.load(f)
        else:
            _CLF = False
    return _CLF or None


def classify(crops: list[Image.Image]) -> list[tuple[str, float]]:
    c = _classifier()
    if c is None or not crops:
        return [("other", 0.0)] * len(crops)
    import torch

    from .backbone import Backbone

    bb = Backbone.get("facebook/dinov2-small", 224)
    sq = []
    for im in crops:
        s = max(im.size)
        canvas = Image.new("RGB", (s, s), tuple(int(v) for v in np.asarray(im).reshape(-1, 3).mean(0)))
        canvas.paste(im, ((s - im.width) // 2, (s - im.height) // 2))
        sq.append(canvas)
    with torch.no_grad():
        g = bb(sq, masking=False)
        f = torch.nn.functional.normalize(torch.cat([g.cls.float(), g.feats.float().mean(1)], 1), dim=1).cpu().numpy()
    p = c["clf"].predict_proba(f)
    return [(c["clf"].classes_[int(i)], float(row[int(i)])) for row, i in zip(p, p.argmax(1))]


# ------------------------------------------------------------------ the board map
@dataclass
class Component:
    id: str
    kind: str
    kind_conf: float
    named_by: str
    bbox: tuple[int, int, int, int]  # x, y, w, h in the golden-board frame (work resolution)
    mask: np.ndarray = field(repr=False)  # bool, full frame
    area: int = 0
    stats: dict = field(default_factory=dict)  # per-feature normal ranges from the good boards

    def public(self, W: int, H: int) -> dict:
        x, y, w, h = self.bbox
        return {"id": self.id, "kind": self.kind, "kindConfidence": round(self.kind_conf, 3), "namedBy": self.named_by,
                "bbox": [x / W, y / H, w / W, h / H], "centroid": [(x + w / 2) / W, (y + h / 2) / H],
                "areaPct": round(100 * self.area / (W * H), 3)}


@dataclass
class BoardMap:
    golden: np.ndarray
    board: np.ndarray
    mask_lab: np.ndarray  # solder-mask colour (L, a, b)
    mask_tol: float
    components: list[Component]
    occupied: np.ndarray  # union of (dilated) component masks
    px_per_mm: float | None = None

    @property
    def shape(self):
        return self.golden.shape

    # ---------------------------------------------------------- build
    @classmethod
    def build(cls, refs: list[Image.Image], ref_heats: list[np.ndarray] | None = None,
              calib: list[tuple[Image.Image, np.ndarray]] | None = None) -> "BoardMap":
        works = [to_work(r) for r in refs]
        base = works[0]
        aligned, warps = [base], [np.eye(2, 3, dtype=np.float32)]
        for w in works[1:]:
            a, wp = align(w, base)
            aligned.append(a)
            warps.append(wp)
        stack = np.stack(aligned)
        golden = np.median(stack, axis=0).astype(np.uint8)
        board = board_mask(golden)
        L = lab(golden)
        px = L[board]
        # solder mask = the dominant colour on the board
        k = 5
        crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1.0)
        sample = px[np.random.default_rng(0).choice(len(px), min(len(px), 40000), replace=False)]
        _, labels, centers = cv2.kmeans(sample, k, None, crit, 3, cv2.KMEANS_PP_CENTERS)
        big = int(np.bincount(labels.ravel(), minlength=k).argmax())
        mask_lab = centers[big]
        d = np.linalg.norm(sample[labels.ravel() == big] - mask_lab, axis=1)
        tol = float(max(12.0, np.percentile(d, 97) * 1.25))
        sub = (np.linalg.norm(L - mask_lab, axis=2) < tol) & board
        # silkscreen (white text and outlines) is thin; pads and metal are thick. Keep white only near a thick core.
        # Measured on VisA boards: silkscreen ink is neutral white (b* ~ 128, L* 195-220); tinned pads and metal
        # are warmer and darker (b* 131-136, L* 160-180). So colour separates them even when the ink is thick.
        chroma = np.linalg.norm(L[..., 1:] - 128, axis=2)
        white = ((L[..., 0] > 165) & (chroma < 28) & board).astype(np.uint8)
        ink = (L[..., 0] > 182) & (np.abs(L[..., 1] - 128) < 4) & (L[..., 2] - 128 < 3.5) & board
        dist = cv2.distanceTransform(white, cv2.DIST_L2, 3)
        core = cv2.dilate((dist > 3.2).astype(np.uint8), np.ones((9, 9), np.uint8))
        silk = ink | (white.astype(bool) & ~core.astype(bool))
        comp = (board & ~sub & ~cv2.dilate(silk.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)).astype(np.uint8)
        comp = cv2.morphologyEx(comp, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))  # drop remaining specks and thin traces
        comp = cv2.morphologyEx(comp, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))  # merge bodies with their pads
        barea = float(board.sum())
        comp = _split_merged(comp, golden, 0.012 * barea)
        n, lab_img, st, _ = cv2.connectedComponentsWithStats(comp, 8)
        cand = []
        for i in range(1, n):
            x, y, w, h, a = st[i]
            if a < 0.0007 * barea or a > 0.3 * barea:
                continue
            m = lab_img == i
            dist = cv2.distanceTransform(m.astype(np.uint8), cv2.DIST_L2, 3)
            if dist.max() < 3.0:  # still a thin line: silkscreen outline, not a part
                continue
            cand.append((x, y, w, h, a, m))
        crops = []
        for x, y, w, h, a, m in cand:
            p = max(3, int(0.15 * max(w, h)))
            crops.append(Image.fromarray(golden[max(0, y - p):y + h + p, max(0, x - p):x + w + p]))
        kinds = classify(crops)
        comps: list[Component] = []
        for (x, y, w, h, a, m), (kind, conf), crop in zip(cand, kinds, crops):
            body = golden[m].astype(np.float32)
            metal = float(((body.mean(1) > 150) & (body.std(1) < 22)).mean())
            fill = a / float(w * h)
            circ = 4 * np.pi * a / max(1.0, cv2.arcLength(max(cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0], key=cv2.contourArea), True)) ** 2
            named = "component classifier"
            if a > 0.04 * barea and metal > 0.35:
                kind, conf, named = "connector", 0.6, "geometry (large metal part)"
            elif metal > 0.25 and a < 0.02 * barea and _dark_centre(golden, x, y, w, h):
                kind, conf, named = "hole / pad", 0.7, "geometry (metal ring around a hole)"
            elif circ > 0.75 and a < 0.01 * barea and metal > 0.3:
                kind, conf, named = "hole / pad", 0.6, "geometry (round metal ring)"
            elif conf < 0.45:
                kind, named = ("metal part" if metal > 0.5 else "other"), "low classifier confidence"
            comps.append(Component(id="", kind=kind, kind_conf=conf, named_by=named, bbox=(int(x), int(y), int(w), int(h)),
                                   mask=m, area=int(a)))
        # designators in reading order per type (R1, R2 ... U1)
        counters: dict = {}
        for c in sorted(comps, key=lambda c: (c.bbox[1] // 40, c.bbox[0])):
            p = PREFIX.get(c.kind, "X")
            counters[p] = counters.get(p, 0) + 1
            c.id = f"{p}{counters[p]}"
        occ = np.zeros(board.shape, np.uint8)
        for c in comps:
            occ |= cv2.dilate(c.mask.astype(np.uint8), np.ones((11, 11), np.uint8))
        bm = cls(golden=golden, board=board, mask_lab=mask_lab, mask_tol=tol, components=comps, occupied=occ.astype(bool))
        bm._learn(aligned, [w.shape for w in works], warps, ref_heats, calib)
        return bm

    # bad-when-high / bad-when-low measurements, with an absolute floor and a margin beyond the calibration extreme
    UPPER = {"offset": (3.0, 2.0), "darkFrac": (0.1, 0.1), "heat": (0.0, 0.0), "terminalRatio": (1.4, 0.2),
             "termDLmax": (10.0, 5.0), "ringMetal": (0.06, 0.04), "rotGain": (0.1, 0.05)}
    LOWER = {"corr": (0.85, 0.1), "dL": (-8.0, 5.0), "termDLmin": (-10.0, 5.0)}
    Z = 5.0  # ~350 checks per board: each must be very unlikely on a good board (robust z, not the extreme)

    def _learn(self, aligned: list[np.ndarray], shapes, warps, heats, calib=None) -> None:
        """Normal range of every per-component measurement. Preferably from separate good boards that were never
        references (exchangeable with future boards); otherwise leave-one-out over the references."""
        rows = {c.id: [] for c in self.components}
        if calib:
            source = f"{len(calib)} separate good boards"
            for img, heat256 in calib:
                work = to_work(img)
                a, warp = align(work, self.golden)
                heat = warp_map(heat256, work.shape, warp, self.shape) if heat256 is not None else None
                for c in self.components:
                    rows[c.id].append(self._measure(a, c, heat, None))
        else:
            source = f"leave-one-out over {len(aligned)} references"
            stack = np.stack(aligned)
            for i in range(len(aligned)):
                golden_i = np.median(np.delete(stack, i, axis=0), axis=0).astype(np.uint8) if len(aligned) > 3 else self.golden
                heat = warp_map(heats[i], shapes[i], warps[i], self.shape) if heats is not None else None
                for c in self.components:
                    rows[c.id].append(self._measure(aligned[i], c, heat, golden_i))
        self.calibration = source
        for c in self.components:
            r = rows[c.id]
            arr = lambda k: np.array([x[k] for x in r if x.get(k) is not None], np.float32)  # noqa: E731
            lim = {}
            for k, (floor, margin) in self.UPPER.items():
                v = arr(k)
                if not len(v):
                    lim[k] = floor
                    continue
                med = float(np.median(v))
                sc = 1.4826 * float(np.median(np.abs(v - med))) + 1e-6
                lim[k] = max(floor, med + self.Z * max(sc, 0.25 * margin), 1.5 * float(np.percentile(v, 95)))
            for k, (floor, margin) in self.LOWER.items():
                v = arr(k)
                if not len(v):
                    lim[k] = floor
                    continue
                med = float(np.median(v))
                sc = 1.4826 * float(np.median(np.abs(v - med))) + 1e-6
                lim[k] = min(floor, med - self.Z * max(sc, 0.25 * margin))
            sub, body = arr("substrate"), arr("bodyFrac")
            c.stats = {
                "offsetMax": lim["offset"], "corrMin": lim["corr"], "dLMin": lim["dL"], "darkMax": lim["darkFrac"],
                "heatMax": lim["heat"] * 1.05, "terminalMax": lim["terminalRatio"], "termLow": lim["termDLmin"],
                "termHigh": lim["termDLmax"], "ringMax": lim["ringMetal"], "rotMax": lim["rotGain"],
                "substrate": float(np.median(sub)) if len(sub) else 0.0,
                "bodyFrac": float(np.median(body)) if len(body) else 0.5,
                "n": len(r),
            }

    def _lab(self, arr: np.ndarray) -> np.ndarray:
        cache = self.__dict__.setdefault("_labcache", [])
        for ref, val in cache:
            if ref is arr:
                return val
        val = lab(arr)
        cache.append((arr, val))
        del cache[:-3]  # the golden board, the current board, and one leave-one-out golden
        return val

    def _geometry(self, c: Component) -> dict:
        g = self.__dict__.setdefault("_geo", {})
        if c.id not in g:
            bm8 = c.mask.astype(np.uint8)
            ring = cv2.dilate(bm8, np.ones((13, 13), np.uint8)).astype(bool) & ~cv2.dilate(bm8, np.ones((3, 3), np.uint8)).astype(bool) & self.board
            near = cv2.dilate(bm8, np.ones((5, 5), np.uint8)).astype(bool)
            g[c.id] = {"ring": np.nonzero(ring), "near": np.nonzero(near)}
            c.pix = np.nonzero(c.mask)
        return g[c.id]

    # ---------------------------------------------------------- measure one component
    def _measure(self, a: np.ndarray, c: Component, heat: np.ndarray | None, golden: np.ndarray | None = None) -> dict:
        golden = self.golden if golden is None else golden
        x, y, w, h = c.bbox
        H, W = a.shape[:2]
        m = max(10, int(0.8 * max(w, h)))  # search far enough to find a part that moved by most of its size
        x0, y0, x1, y1 = max(0, x - m), max(0, y - m), min(W, x + w + m), min(H, y + h + m)
        win = _gray(a[y0:y1, x0:x1])
        tpl = _gray(golden[y:y + h, x:x + w])
        out = {}
        if tpl.std() < 2 or win.shape[0] < tpl.shape[0] or win.shape[1] < tpl.shape[1]:
            out.update(corr=1.0, offset=0.0, dx=0.0, dy=0.0, rotGain=0.0, corr0=1.0)
        else:
            res = cv2.matchTemplate(win, tpl, cv2.TM_CCOEFF_NORMED)
            gy, gx = np.mgrid[0:res.shape[0], 0:res.shape[1]]
            dist = np.hypot(gx - (x - x0), gy - (y - y0)) / max(w, h)
            pen = res - 0.25 * dist  # a look-alike neighbour must match clearly better to win
            iy, ix = np.unravel_index(int(np.argmax(pen)), pen.shape)
            mx = float(res[iy, ix])
            dx, dy = ix - (x - x0), iy - (y - y0)
            out.update(corr=mx, dx=float(dx), dy=float(dy), offset=float(np.hypot(dx, dy)),
                       corr0=float(res[y - y0, x - x0]))
            # orientation: only meaningful when the golden part does NOT look like itself turned
            self_rot, best_rot = -1.0, -1.0
            local = _gray(a[max(0, y - 4):y + h + 4, max(0, x - 4):x + w + 4])
            for k in (1, 2, 3):
                t = np.ascontiguousarray(np.rot90(tpl, k))
                if t.std() <= 2:
                    continue
                if t.shape == tpl.shape:
                    self_rot = max(self_rot, float(cv2.matchTemplate(tpl, t, cv2.TM_CCOEFF_NORMED).max()))
                if t.shape[0] <= local.shape[0] and t.shape[1] <= local.shape[1]:
                    best_rot = max(best_rot, float(cv2.matchTemplate(local, t, cv2.TM_CCOEFF_NORMED).max()))
            out["rotGain"] = float(best_rot - out["corr0"]) if self_rot < 0.55 else 0.0
            out["rotCorr"] = float(best_rot)
        body = c.mask
        La_all, Lg_all = self._lab(a), self._lab(golden)  # converted once per board, not once per component
        sx, sy = int(out.get("dx", 0)), int(out.get("dy", 0))
        if not (out.get("offset", 0) <= 0.6 * max(w, h)):
            sx = sy = 0
        ys, xs = c.pix if getattr(c, "pix", None) is not None else np.nonzero(body)
        Hh, Ww = a.shape[:2]
        ys2, xs2 = np.clip(ys + sy, 0, Hh - 1), np.clip(xs + sx, 0, Ww - 1)  # read the part where it actually sits
        La, Lg = La_all[ys2, xs2], Lg_all[ys, xs]

        def metal(L):
            return (L[:, 0] > 140) & (np.linalg.norm(L[:, 1:] - 128, axis=1) < 30)

        def substrate(L):
            return np.linalg.norm(L - self.mask_lab, axis=1) < self.mask_tol

        out["substrate"] = float(substrate(La).mean())
        out["bodyFrac"] = float((~substrate(La) & ~metal(La)).mean())
        out["darkFrac"] = float((La[:, 0] < 55).mean() - (Lg[:, 0] < 55).mean())
        horiz = w >= h
        t = xs if horiz else ys
        lo, hi = np.percentile(t, 25), np.percentile(t, 75)
        ends = [(t <= lo), (t >= hi)]
        mid = ~ends[0] & ~ends[1]
        out["dL"] = float(La[mid, 0].mean() - Lg[mid, 0].mean()) if mid.any() else float(La[:, 0].mean() - Lg[:, 0].mean())
        tdl = [float(La[e, 0].mean() - Lg[e, 0].mean()) if e.any() else 0.0 for e in ends]
        out["termDLmin"], out["termDLmax"] = min(tdl), max(tdl)
        names = ("left", "right") if horiz else ("top", "bottom")
        out["termDark"] = names[int(np.argmin(tdl))]
        out["termBright"] = names[int(np.argmax(tdl))]
        geo = self._geometry(c)
        ry, rx = geo["ring"]
        if len(ry):
            out["ringMetal"] = float(metal(La_all[np.clip(ry + sy, 0, Hh - 1), np.clip(rx + sx, 0, Ww - 1)]).mean() - metal(Lg_all[ry, rx]).mean())
        if heat is not None:
            hy, hx = geo["near"]
            hb = heat[hy, hx]
            out["heat"] = float(hb.max()) if hb.size else 0.0
            hv = heat[ys, xs]
            term = ends[0] | ends[1]
            out["terminalRatio"] = float((hv[term].mean() + 1e-6) / (hv[~term].mean() + 1e-6)) if (~term).any() else 1.0
            out["terminal"] = names[0] if hv[ends[0]].mean() >= hv[ends[1]].mean() else names[1]
        return out

    # ---------------------------------------------------------- diagnose a new board
    def diagnose(self, img: Image.Image, heat256: np.ndarray | None, tau_pass: float) -> dict:
        work = to_work(img)
        a, warp = align(work, self.golden)
        heat = warp_map(heat256, work.shape, warp, self.shape) if heat256 is not None else None
        results = []
        for c in self.components:
            f = self._measure(a, c, heat, None)
            s = c.stats
            status, why = "OK", []
            hot = heat is not None and f.get("heat", 0) > max(s["heatMax"], tau_pass)
            gone = f["substrate"] - s["substrate"] > 0.25 or s["bodyFrac"] - f["bodyFrac"] > 0.35
            polar = c.kind in ("IC", "diode / LED", "transistor", "other")
            if f["corr"] < s["corrMin"] and gone:
                status = "MISSING"
                why.append(f"its body is gone: {round(100 * f['bodyFrac'])}% of the footprint is still part body (good boards: {round(100 * s['bodyFrac'])}%)")
            elif polar and f.get("rotGain", 0) > s["rotMax"] and f.get("rotCorr", 0) > 0.7 and f.get("corr0", 1) < s["corrMin"] + 0.1:
                status = "ROTATED"
                why.append(f"matches the golden part {f['rotGain']:.2f} better when turned (orientation / polarity)")
            elif f["offset"] > s["offsetMax"] and f["corr"] >= s["corrMin"] and f["corr"] - f.get("corr0", f["corr"]) > 0.15:
                status = "SHIFTED"
                why.append(f"moved {f['dx']:+.0f} px, {f['dy']:+.0f} px (good boards: under {s['offsetMax']:.0f} px)")
            elif f["dL"] < s["dLMin"] or f["darkFrac"] > s["darkMax"] or (
                    f.get("termDLmin", 0) < s["termLow"] and f.get("termDLmax", 0) < 0.5 * s["termLow"]):  # both ends charred
                status = "BURNT"
                why.append(f"body {-f['dL']:.0f} units darker than the golden part (good boards: at most {-s['dLMin']:.0f})")
            elif f.get("termDLmin", 0) < s["termLow"]:
                status = "SOLDER"
                why.append(f"{f['termDark']} joint {-f['termDLmin']:.0f} units duller than on good boards: dry or insufficient solder")
            elif f.get("ringMetal", 0) > s["ringMax"] or f.get("termDLmax", 0) > s["termHigh"]:
                status = "SOLDER"
                why.append(f"new bright metal around the {f['termBright']} joint ({round(100 * f.get('ringMetal', 0))}% of the surround): excess solder or a bridge")
            elif hot and f.get("terminalRatio", 0) > s["terminalMax"]:
                status = "SOLDER"
                why.append(f"anomaly {f['terminalRatio']:.1f}x stronger at the {f.get('terminal', 'end')} joint than on the body")
            elif f["corr"] < s["corrMin"] and hot:
                status = "WRONG_PART"
                why.append(f"looks like a different part (match {f['corr']:.2f}, good boards ≥ {s['corrMin'] + 0.12:.2f})")
            elif hot:
                status = "DAMAGED"
                why.append(f"patch-memory anomaly {f['heat']:.3f} above anything seen on good boards ({s['heatMax']:.3f})")
            results.append({"id": c.id, "status": status, "why": why,
                            "measured": {k: round(v, 3) if isinstance(v, float) else v for k, v in f.items()}})
        extra = []
        if heat is not None:
            hm = heat
            m = cv2.morphologyEx((hm > 0.85 * tau_pass).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            n, lab_img, st, cent = cv2.connectedComponentsWithStats(m, 8)
            H, W = hm.shape
            for i in range(1, n):
                if st[i, 4] < 25:
                    continue
                reg = lab_img == i
                inside = (reg & self.occupied).sum() / float(reg.sum())
                if inside < 0.3 and (reg & self.board).any():
                    x, y, w, h = (int(v) for v in st[i, :4])
                    extra.append({"id": f"E{len(extra) + 1}", "status": "EXTRA", "bbox": [x / W, y / H, w / W, h / H],
                                  "centroid": [float(cent[i][0]) / W, float(cent[i][1]) / H], "peak": round(float(hm[reg].max()), 4),
                                  "why": [_extra_why(work_aligned := a, reg, self)]})
        bad = [r for r in results if r["status"] != "OK"]
        return {"_aligned": a, "components": results, "extra": extra[:4], "faults": len(bad) + len(extra[:4]),
                "summary": {k: sum(r["status"] == k for r in results) for k in STATUS_TEXT if k != "EXTRA"} | {"EXTRA": len(extra[:4])}}

    # ---------------------------------------------------------- X-ray: physical layers + copper connectivity
    def layers(self) -> dict:
        """Split the golden board into its physical layers (all measured from the photo, nothing drawn):
        substrate (board outline), copper (traces visible under the mask + exposed pads), solder mask, silkscreen ink,
        components. Then trace the copper to find which components are wired to which."""
        cached = getattr(self, "_layers", None)
        if cached is not None:
            return cached
        g = self.golden
        L = lab(g)
        board = self.board
        dist_mask = np.linalg.norm(L - self.mask_lab, axis=2)
        mask_px = (dist_mask < self.mask_tol * 1.4) & board
        comp_any = np.zeros(board.shape, bool)
        for c in self.components:
            comp_any |= c.mask
        chroma = np.linalg.norm(L[..., 1:] - 128, axis=2)
        ink = (L[..., 0] > 182) & (np.abs(L[..., 1] - 128) < 4) & (L[..., 2] - 128 < 3.5) & board & ~comp_any
        metal = (L[..., 0] > 140) & (chroma < 30) & board & ~ink
        # copper under the solder mask is a slightly lighter shade of the mask colour (thin, long structures)
        Lm = L[..., 0][mask_px]
        lighter = mask_px & (L[..., 0] > np.median(Lm) + max(6.0, 0.8 * np.std(Lm)))
        lighter = cv2.morphologyEx(lighter.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8)).astype(bool)
        copper = lighter | (metal & ~comp_any) | (metal & comp_any)
        copper = cv2.morphologyEx(copper.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)).astype(bool)
        soldermask = mask_px & ~lighter

        def rgba(mask: np.ndarray, colour=None, from_photo=True, alpha=255) -> str:
            import base64
            import io

            h, w = mask.shape
            out = np.zeros((h, w, 4), np.uint8)
            if from_photo:
                out[..., :3] = g
            if colour is not None:
                out[..., :3] = colour
            out[..., 3] = mask.astype(np.uint8) * alpha
            buf = io.BytesIO()
            Image.fromarray(out, "RGBA").save(buf, format="PNG", optimize=True)
            return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

        # connectivity: copper regions touching two or more components are a net between them
        cop_only = (copper & ~comp_any).astype(np.uint8)
        n, lab_img = cv2.connectedComponents(cop_only, 8)
        touch: dict = {}
        dil = {c.id: cv2.dilate(c.mask.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool) for c in self.components}
        for cid, dm in dil.items():
            for k in np.unique(lab_img[dm & cop_only.astype(bool)]):
                if k:
                    touch.setdefault(int(k), set()).add(cid)
        H, W = board.shape
        edges, nets = {}, []
        for k, ids in touch.items():
            if len(ids) < 2 or len(ids) > 8:  # a ground pour touching everything says nothing about wiring
                continue
            ys, xs = np.nonzero(lab_img == k)
            if len(xs) < 15:
                continue
            nets.append({"id": f"N{len(nets) + 1}", "components": sorted(ids), "px": int(len(xs)),
                         "centroid": [float(xs.mean()) / W, float(ys.mean()) / H]})
            ids = sorted(ids)
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    e = edges.setdefault((ids[i], ids[j]), {"a": ids[i], "b": ids[j], "nets": []})
                    e["nets"].append(nets[-1]["id"])
        self._layers = {
            "size": [W, H],
            "layers": [
                {"key": "substrate", "title": "Substrate (FR-4)", "image": rgba(board, colour=(196, 170, 104), from_photo=False),
                 "what": "the glass-fibre board itself, outline cut from the photo"},
                {"key": "copper", "title": "Copper", "image": rgba(copper, colour=(214, 140, 72), from_photo=False),
                 "what": "traces seen through the mask (a lighter shade of it) and exposed pads"},
                {"key": "mask", "title": "Solder mask", "image": rgba(soldermask, alpha=235),
                 "what": f"the coloured protective coat (its colour learned from the board: L*a*b* {', '.join(f'{v:.0f}' for v in self.mask_lab)})"},
                {"key": "silk", "title": "Silkscreen", "image": rgba(cv2.dilate(ink.astype(np.uint8), np.ones((2, 2), np.uint8)).astype(bool), colour=(245, 245, 240), from_photo=False),
                 "what": "printed labels and outlines (neutral white ink)"},
                {"key": "parts", "title": "Components", "image": rgba(cv2.dilate(comp_any.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)),
                 "what": f"{len(self.components)} parts found on the golden board"},
            ],
            "coverage": {"copperPct": round(100 * copper.sum() / max(1, board.sum()), 1), "maskPct": round(100 * soldermask.sum() / max(1, board.sum()), 1),
                         "silkPct": round(100 * ink.sum() / max(1, board.sum()), 1), "partsPct": round(100 * comp_any.sum() / max(1, board.sum()), 1)},
            "nets": nets, "edges": list(edges.values()),
            "note": "Connectivity is read from copper visible through the mask on one side of the board: vias and inner layers are invisible, so this is a partial netlist.",
        }
        return self._layers

    # ---------------------------------------------------------- for the dashboard
    def public(self) -> dict:
        H, W = self.shape[:2]
        kinds: dict = {}
        for c in self.components:
            kinds[c.kind] = kinds.get(c.kind, 0) + 1
        return {"components": [c.public(W, H) for c in self.components], "kinds": kinds, "size": [W, H],
                "statusText": STATUS_TEXT}
