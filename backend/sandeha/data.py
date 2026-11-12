"""Dataset access for public industrial anomaly datasets (VisA, MAD-Sim).

All data comes from the internet:
  * VisA  - Amazon, AWS Open Data, CC BY 4.0            -> data/visa
  * MAD-Sim (PAD, NeurIPS'23) - CC BY-NC-SA 4.0            -> data/mad/MAD-Sim
"""
from __future__ import annotations

import csv
import functools
import json
import random
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"
VISA_ROOT = DATA_ROOT / "visa"
MAD_ROOT = DATA_ROOT / "mad" / "MAD-Sim"
UPLOAD_ROOT = DATA_ROOT / "uploads"
IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@dataclass
class Sample:
    path: Path
    label: int  # 0 good, 1 defect
    defect_type: str = "good"
    mask_path: Path | None = None
    pose: np.ndarray | None = None  # 4x4 camera-to-world (MAD train only)
    meta: dict = field(default_factory=dict)

    def image(self, size: int | None = None) -> Image.Image:
        im = Image.open(self.path).convert("RGB")
        return im.resize((size, size), Image.BICUBIC) if size else im

    def mask(self, size: int | None = None) -> np.ndarray | None:
        if self.mask_path is None or not self.mask_path.exists():
            return None
        m = Image.open(self.mask_path).convert("L")
        if size:
            m = m.resize((size, size), Image.NEAREST)
        return (np.asarray(m) > 0).astype(np.uint8)


@dataclass
class Product:
    name: str
    source: str
    train_good: list[Sample]
    test: list[Sample]
    fov_x: float | None = None  # MAD camera_angle_x (radians)

    def few_shot(self, n_good: int = 30, n_defect: int = 5, seed: int = 0):
        """The PS-12 protocol: <=30 good references and <=5 labelled defects; the rest is evaluation."""
        rng = random.Random(seed)
        good = rng.sample(self.train_good, min(n_good, len(self.train_good)))
        defects = [s for s in self.test if s.label == 1]  # label -1 = unlabelled uploaded test image
        rng.shuffle(defects)
        known = defects[:n_defect]
        known_ids = {id(s) for s in known}
        evaluation = [s for s in self.test if id(s) not in known_ids]
        return good, known, evaluation


def visa_categories() -> list[str]:
    return sorted(p.name for p in VISA_ROOT.iterdir() if (p / "Data").is_dir())


def load_visa(name: str) -> Product:
    split = VISA_ROOT / "split_csv" / "1cls.csv"
    anno = {}
    anno_file = VISA_ROOT / name / "image_anno.csv"
    if anno_file.exists():
        with open(anno_file, newline="") as f:
            for row in csv.DictReader(f):
                anno[row["image"]] = row.get("label", "")
    train, test = [], []
    with open(split, newline="") as f:
        for row in csv.DictReader(f):
            if row["object"] != name:
                continue
            is_def = row["label"] == "anomaly"
            s = Sample(path=VISA_ROOT / row["image"], label=int(is_def),
                       defect_type=(anno.get(row["image"]) or "anomaly") if is_def else "good",
                       mask_path=(VISA_ROOT / row["mask"]) if row["mask"] else None)
            (train if row["split"] == "train" else test).append(s)
    return Product(name=name, source="VisA", train_good=[s for s in train if s.label == 0], test=test)


def mad_categories() -> list[str]:
    return sorted(p.name for p in MAD_ROOT.iterdir() if p.is_dir())


def load_mad(name: str) -> Product:
    root = MAD_ROOT / name
    tf = json.loads((root / "transforms.json").read_text())
    poses = {Path(fr["file_path"]).name: np.array(fr["transform_matrix"], dtype=np.float32) for fr in tf["frames"]}
    train = [Sample(path=p, label=0, pose=poses.get(p.name)) for p in
             sorted((root / "train" / "good").glob("*.png"), key=lambda p: int(p.stem))]
    test = []
    for d in sorted((root / "test").iterdir()):
        for p in sorted(d.glob("*.png"), key=lambda p: int(p.stem)):
            is_def = d.name != "good"
            m = root / "ground_truth" / d.name / f"{p.stem}_mask.png"
            test.append(Sample(path=p, label=int(is_def), defect_type=d.name if is_def else "good",
                               mask_path=m if is_def else None))
    return Product(name=name, source="MAD-Sim", train_good=train, test=test, fov_x=float(tf["camera_angle_x"]))


@functools.lru_cache(maxsize=64)
def load_upload(uid: str) -> Product:
    """A product the user uploaded: good/ (references), defect/ (optional known defects), test/ (to inspect)."""
    root = UPLOAD_ROOT / uid
    meta = json.loads((root / "meta.json").read_text()) if (root / "meta.json").exists() else {}
    files = lambda d: sorted(p for p in (root / d).glob("*") if p.suffix.lower() in IMG_EXT) if (root / d).exists() else []
    good = [Sample(path=p, label=0) for p in files("good")]
    test = [Sample(path=p, label=1, defect_type=meta.get("defectLabel", "uploaded defect")) for p in files("defect")]
    unknown = [Sample(path=p, label=-1, defect_type="unknown") for p in files("test")]
    prod = Product(name=meta.get("name", uid), source="Upload", train_good=good, test=test + unknown)
    return prod


def load(source: str, name: str) -> Product:
    if source.lower() == "upload":
        return load_upload(name)
    return load_visa(name) if source.lower() == "visa" else load_mad(name)


def catalog() -> list[dict]:
    out = []
    if VISA_ROOT.exists():
        out += [{"source": "VisA", "name": c} for c in visa_categories()]
    if MAD_ROOT.exists():
        out += [{"source": "MAD-Sim", "name": c} for c in mad_categories()]
    if UPLOAD_ROOT.exists():
        out += [{"source": "Upload", "name": p.name} for p in sorted(UPLOAD_ROOT.iterdir()) if (p / "good").exists()]
    return out
