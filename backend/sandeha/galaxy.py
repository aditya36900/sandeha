"""Memory Galaxy: a 3D map of everything the AI has seen.

Each product is its own constellation: a 3D UMAP of its reference parts and inspected parts
(global DINOv2 embeddings), normalised to a fixed size and placed on a ring so that differences
*within* a product stay visible. Good parts land inside the constellation, defects drift to its
edge, and genuinely novel parts land in empty space - which is why the AI says "I've never seen this".
"""
from __future__ import annotations

import math

import numpy as np


def _embed(X: np.ndarray) -> np.ndarray:
    if len(X) < 12:
        Xc = X - X.mean(0)
        _, _, vt = np.linalg.svd(Xc, full_matrices=False)
        Y = Xc @ vt[:3].T
    else:
        import umap

        Y = umap.UMAP(n_components=3, n_neighbors=min(15, len(X) - 1), min_dist=0.3, metric="cosine",
                      random_state=7).fit_transform(X)
    Y = Y - np.median(Y, axis=0)
    scale = np.percentile(np.linalg.norm(Y, axis=1), 90) + 1e-6
    return Y / scale  # 90% of stars within radius 1


def build(sessions) -> dict:
    ready = [s for s in sessions if hasattr(s, "gref")]
    if not ready:
        return {"points": [], "products": []}
    points = []
    n = len(ready)
    ring = 0.0 if n == 1 else 2.6
    for si, s in enumerate(ready):
        g = s.galaxy_payload()
        X = np.concatenate([g["refs"], g["parts"]]) if len(g["parts"]) else g["refs"]
        Y = _embed(X.astype(np.float32))
        a = 2 * math.pi * si / max(n, 1)
        centre = np.array([ring * math.cos(a), 0.0, ring * math.sin(a)])
        Y = Y * 1.1 + centre
        k = len(g["refs"])
        for i in range(k):
            points.append({"session": s.id, "product": s.product.name, "kind": "reference", "productIndex": si,
                           "position": [round(float(v), 3) for v in Y[i]]})
        for r, y in zip(g["records"], Y[k:]):
            points.append({"session": s.id, "product": s.product.name, "kind": "part", "record": r.id, "decision": r.decision,
                           "truth": r.truth, "productIndex": si, "image": r.image_url,
                           "position": [round(float(v), 3) for v in y]})
    return {"points": points, "products": [{"session": s.id, "name": s.product.name, "source": s.source, "plant": s.plant}
                                            for s in ready]}
