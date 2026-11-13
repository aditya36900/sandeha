"""The demo tray: the same hand-checked boards in the same order on every run, one for each situation the station
handles (clean pass, each defect type, a borderline board that goes to a person, a blurred and a dark photo, a
different board type, and something that is not a board at all).

The list lives in data/results/demo_tray.json and is built and verified by scripts/build_demo_tray.py: every board in
it was put through the station and behaved as described. Nothing on the tray tells the station the answer; the truth
and the caption stay on the server until a board is scanned.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

from . import data

MANIFEST = data.DATA_ROOT / "results" / "demo_tray.json"


@dataclass
class DemoSample:
    path: Path
    kind: str                 # board | blur | dark | other_board | not_board
    label: int                # 0 good, 1 defect, -1 not a judgeable board
    defect_type: str = "good"
    meta: dict = field(default_factory=dict)   # {slot, title, expect}

    def image(self, size: int | None = None) -> Image.Image:
        im = Image.open(self.path).convert("RGB")
        if self.kind == "blur":       # camera out of focus / board moving
            im = im.filter(ImageFilter.GaussianBlur(radius=max(6, im.width // 110)))
        elif self.kind == "dark":     # lamp failed
            im = ImageEnhance.Brightness(im).enhance(0.2)
        return im.resize((size, size), Image.BICUBIC) if size else im


def tray(product: str) -> list[DemoSample]:
    if not MANIFEST.exists():
        return []
    rows = json.loads(MANIFEST.read_text()).get(product, {}).get("items", [])
    out = []
    for i, r in enumerate(rows):
        p = data.VISA_ROOT / r["path"]
        if not p.exists():
            return []  # dataset not downloaded: fall back to a random tray
        out.append(DemoSample(path=p, kind=r["kind"], label=int(r["truth"]), defect_type=r.get("defect", "good"),
                              meta={"slot": i + 1, "title": r["title"], "expect": r["expect"]}))
    return out
