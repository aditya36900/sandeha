"""How many good photos does the station really need? Measured, not claimed.

For each PCB: learn from N good photos (N = 1, 2, 5, 10, 20, 30), with NO defect photo and NO training step, then
score the held-out VisA test boards. Three random draws of the references per N. The alarm line for each run comes
from 40 separate good boards (98th percentile), so "caught" and "false alarms" are honest operating numbers.

Also saves the picture behind the curve: the same defective board's heat map as N grows, on one fixed colour scale.

usage: python scripts/fewshot_curve.py [pcb1 pcb2 pcb3 pcb4]
writes: data/results/fewshot.json and data/results/fewshot/*.jpg
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402
from sklearn.metrics import roc_auc_score  # noqa: E402

from sandeha import data  # noqa: E402
from sandeha.backbone import Backbone  # noqa: E402
from sandeha.memory import PatchMemory  # noqa: E402

NS = [1, 2, 5, 10, 20, 30]
SEEDS = 3
OUT = data.DATA_ROOT / "results"
IMG = OUT / "fewshot"
SIDE = 384


def small(s) -> Image.Image:
    return s.image().resize((640, 640), Image.BICUBIC)


def grids(bb, images, bs=8):
    return [bb(images[i:i + bs], masking=True) for i in range(0, len(images), bs)]


def score(mem, gs):
    sc, dists = [], []
    for g in gs:
        d = mem.distances(g)
        sc.append(mem.score(d, g.fg).cpu().numpy())
        dists.append((d, g.fg))
    return np.concatenate(sc), dists


def heat_frame(img: Image.Image, hm: np.ndarray, lo: float, hi: float) -> np.ndarray:
    base = cv2.cvtColor(np.asarray(img.resize((SIDE, SIDE))), cv2.COLOR_RGB2BGR)
    a = np.clip((hm - lo) / max(1e-6, hi - lo), 0, 1)
    col = cv2.applyColorMap((a * 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
    a3 = (0.15 + 0.75 * a)[..., None] * (a > 0.02)[..., None]
    grey = cv2.cvtColor(cv2.cvtColor(base, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    return (grey * 0.55 * (1 - a3) + col * a3 + grey * 0.0).astype(np.uint8)


def run(name: str, pictures_only: bool = False) -> dict:
    bb = Backbone.get("facebook/dinov2-small", 448)
    prod = data.load("VisA", name)
    rng = random.Random(0)
    goods = list(prod.train_good)
    rng.shuffle(goods)
    calib = goods[:40]                       # only sets the alarm line; never learned from
    pool = goods[40:]
    test = prod.test
    y = np.array([s.label for s in test])
    print(name, "test", len(test), "defects", int(y.sum()), flush=True)
    g_test = grids(bb, [small(s) for s in test])
    g_cal = grids(bb, [small(s) for s in calib])

    rows = {n: [] for n in NS}
    keep = {}                                # seed 0 memories' distance maps, for the pictures
    refs0 = None
    for seed in range(1 if pictures_only else SEEDS):
        r = random.Random(100 + seed)
        refs = r.sample(pool, 30)            # nested: N photos = the first N of these 30
        if seed == 0:
            refs0 = refs
        ref_imgs = [small(s) for s in refs]
        for n in NS:
            mem = PatchMemory(bb).fit(ref_imgs[:n], masking=True)
            sc, dists = score(mem, g_test)
            cal, _ = score(mem, g_cal)
            line = float(np.quantile(cal, 0.98))
            rows[n].append({"auroc": float(roc_auc_score(y, sc)),
                            "caught": float((sc[y == 1] > line).mean()),
                            "falseAlarms": float((sc[y == 0] > line).mean()),
                            "patches": int(mem.bank.shape[0])})
            if seed == 0:
                keep[n] = (mem.hw, [(d.cpu(), fg.cpu()) for d, fg in dists], sc, line)
            del mem
            torch.cuda.empty_cache()
        print(name, "seed", seed, {n: round(rows[n][-1]["auroc"], 3) for n in NS}, flush=True)

    # ---- pictures: two defective boards where the effect of more photos is visible. Both are caught with 30 photos
    # and the hottest spot is on the real defect; among those, the ones whose map was noisiest with 1 photo.
    IMG.mkdir(parents=True, exist_ok=True)
    sc30, line30 = keep[30][2], keep[30][3]
    def hm_of(n, i):
        hw, dists, _, _ = keep[n]
        d, fg = dists[i // 8]
        m = d[i % 8].masked_fill(~fg[i % 8], 0.0).reshape(1, 1, *hw)
        m = torch.nn.functional.interpolate(m, size=(SIDE, SIDE), mode="bilinear", align_corners=False)
        return torch.nn.functional.avg_pool2d(m, 9, 1, 4)[0, 0].numpy()

    scored = []
    for i in range(len(test)):
        if y[i] != 1 or sc30[i] <= line30 or not (test[i].mask_path and test[i].mask_path.exists()):
            continue
        mk = cv2.resize((test[i].mask(None) * 255).astype(np.uint8), (SIDE, SIDE), interpolation=cv2.INTER_NEAREST)
        mk = cv2.dilate(mk, np.ones((31, 31), np.uint8)) > 0
        h30 = hm_of(30, i)
        py, px = np.unravel_index(int(h30.argmax()), h30.shape)
        if not mk[py, px]:
            continue
        lo, hi = float(line30) * 0.9, float(h30.max())
        noise = lambda n: float(np.clip((hm_of(n, i) - lo) / max(1e-6, hi - lo), 0, 1)[~mk].mean())
        scored.append((noise(1) - noise(30), i))
    scored.sort(reverse=True)
    types, picks = set(), []
    for _, i in scored:
        t = test[i].defect_type.split(",")[0].strip()
        if t not in types:
            types.add(t)
            picks.append(int(i))
        if len(picks) == 2:
            break

    examples = []
    for k, i in enumerate(picks):
        img = small(test[i])
        hi = float(hm_of(30, i).max())
        lo = float(line30) * 0.9
        for n in NS:
            cv2.imwrite(str(IMG / f"{name}_{k}_n{n}.jpg"), heat_frame(img, hm_of(n, i), lo, hi), [cv2.IMWRITE_JPEG_QUALITY, 82])
        base = cv2.cvtColor(np.asarray(img.resize((SIDE, SIDE))), cv2.COLOR_RGB2BGR)
        mask = cv2.resize((test[i].mask(None) * 255).astype(np.uint8), (SIDE, SIDE), interpolation=cv2.INTER_NEAREST)
        cs, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(base, cs, -1, (40, 255, 214), 2)
        cv2.imwrite(str(IMG / f"{name}_{k}_truth.jpg"), base, [cv2.IMWRITE_JPEG_QUALITY, 85])
        examples.append({"k": k, "defect": test[i].defect_type,
                         "scores": {str(n): round(float(keep[n][2][i]), 4) for n in NS},
                         "lines": {str(n): round(float(keep[n][3]), 4) for n in NS}})

    # the 30 reference photos of draw 0 as one 6x5 contact sheet
    t = 96
    sheet = np.zeros((5 * t, 6 * t, 3), np.uint8)
    for j, s in enumerate(refs0):
        th = cv2.cvtColor(np.asarray(s.image().resize((t, t), Image.BICUBIC)), cv2.COLOR_RGB2BGR)
        sheet[(j // 6) * t:(j // 6 + 1) * t, (j % 6) * t:(j % 6 + 1) * t] = th
    cv2.imwrite(str(IMG / f"{name}_refs.jpg"), sheet, [cv2.IMWRITE_JPEG_QUALITY, 80])

    if pictures_only:
        return {"examples": examples}
    agg = lambda n, key: [x[key] for x in rows[n]]
    return {"product": name, "testBoards": len(test), "defectBoards": int(y.sum()), "goodBoards": int((y == 0).sum()),
            "draws": SEEDS, "examples": examples,
            "curve": [{"n": n,
                       "auroc": round(float(np.mean(agg(n, "auroc"))), 4), "aurocMin": round(min(agg(n, "auroc")), 4),
                       "aurocMax": round(max(agg(n, "auroc")), 4),
                       "caught": round(float(np.mean(agg(n, "caught"))), 4),
                       "falseAlarms": round(float(np.mean(agg(n, "falseAlarms"))), 4),
                       "patches": int(np.mean(agg(n, "patches")))} for n in NS]}


if __name__ == "__main__":
    pics = "--pictures" in sys.argv
    names = [a for a in sys.argv[1:] if not a.startswith("--")] or ["pcb1", "pcb2", "pcb3", "pcb4"]
    f = OUT / "fewshot.json"
    out = json.loads(f.read_text()) if f.exists() else {"ns": NS, "products": {}}
    out["ns"] = NS
    out["note"] = ("Learned from N good photos only: no defect photo, no training step, no labels. Scored on the held-out VisA "
                   "test boards. Mean of 3 random draws of the reference photos; the band is the worst and best draw. This is the "
                   "patch-memory detector alone, before the golden-board check and the component check are added on top.")
    for nm in names:
        if pics and nm in out["products"]:  # redo only the pictures; the measured curve is kept
            out["products"][nm]["examples"] = run(nm, True)["examples"]
        else:
            out["products"][nm] = run(nm)
        f.write_text(json.dumps(out, indent=1))
    print("wrote", f)
