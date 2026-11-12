"""Train the component-type classifier: frozen DINOv2-S CLS + patch-mean features -> logistic regression.

Data: ParsaVictor/pcb-component-classifier (MIT licence, 1,120 photographed SMD components, 6 classes).
Scored on the dataset's own 120-image holdout, which is never used for training or tuning.
Writes data/results/component_clf.pkl and data/results/component_clf.json.
"""
from __future__ import annotations

import glob
import json
import os
import pickle
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import confusion_matrix  # noqa: E402

from sandeha.backbone import Backbone  # noqa: E402

ROOT = Path(__file__).resolve().parents[2] / "data"
NAMES = {"resistors": "resistor", "capacitors": "capacitor", "diodes": "diode / LED", "inductors": "inductor",
         "transistors": "transistor", "ICs": "IC"}


def load(split: str):
    files = sorted(glob.glob(str(ROOT / "components" / split / "**" / "*.png"), recursive=True))
    ys = [NAMES[re.match(r"([A-Za-z]+)_\d+", os.path.basename(f)).group(1)] for f in files]
    return files, ys


@torch.no_grad()
def embed(bb: Backbone, images: list[Image.Image]) -> np.ndarray:
    """Square-pad (components are long and thin), then CLS + mean patch feature."""
    out = []
    for i in range(0, len(images), 32):
        sq = []
        for im in images[i:i + 32]:
            im = im.convert("RGB")
            s = max(im.size)
            canvas = Image.new("RGB", (s, s), tuple(int(v) for v in np.asarray(im).reshape(-1, 3).mean(0)))
            canvas.paste(im, ((s - im.width) // 2, (s - im.height) // 2))
            sq.append(canvas)
        g = bb(sq, masking=False)
        f = torch.cat([g.cls.float(), g.feats.float().mean(1)], 1)
        out.append(torch.nn.functional.normalize(f, dim=1).cpu().numpy())
    return np.concatenate(out)


def main():
    bb = Backbone.get("facebook/dinov2-small", 224)
    import hashlib

    ftr, ytr = load("train")
    fho, yho = load("holdout")
    digest = lambda f: hashlib.md5(open(f, "rb").read()).hexdigest()  # noqa: E731
    held = {digest(f) for f in fho}
    seen, keep = set(), []
    for f, y in zip(ftr, ytr):  # the archive repeats some photos: drop exact duplicates and any copy of a holdout photo
        d = digest(f)
        if d not in held and d not in seen:
            seen.add(d)
            keep.append((f, y))
    ftr, ytr = [f for f, _ in keep], [y for _, y in keep]
    Xtr = embed(bb, [Image.open(f) for f in ftr])
    Xho = embed(bb, [Image.open(f) for f in fho])
    clf = LogisticRegression(max_iter=4000, C=4.0, class_weight="balanced").fit(Xtr, ytr)
    pred = clf.predict(Xho)
    acc = float((pred == np.array(yho)).mean())
    labels = sorted(set(ytr))
    per = {c: float((pred[np.array(yho) == c] == c).mean()) for c in labels}
    cm = confusion_matrix(yho, pred, labels=labels).tolist()
    (ROOT / "results").mkdir(exist_ok=True)
    with open(ROOT / "results" / "component_clf.pkl", "wb") as f:
        pickle.dump({"clf": clf, "labels": labels, "backbone": "facebook/dinov2-small@224"}, f)
    res = {"dataset": "ParsaVictor/pcb-component-classifier (MIT)", "train": len(ytr), "holdout": len(yho),
           "holdoutAccuracy": round(acc, 3), "perClassRecall": {k: round(v, 3) for k, v in per.items()},
           "labels": labels, "confusion": cm}
    (ROOT / "results" / "component_clf.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res))


if __name__ == "__main__":
    main()
