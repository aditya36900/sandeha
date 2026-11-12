"""Restore everything the repository does not store: public datasets and the local AI models.

  python backend/scripts/download_data.py            # VisA + component photos + the models the station uses
  python backend/scripts/download_data.py --mad      # also MAD-Sim (multi-view objects for the 3D twin demo)
  python backend/scripts/download_data.py --big-vlm  # also Qwen2.5-VL-7B (needs a GPU with ~8 GB free)

All sources are public: VisA (Amazon, CC BY 4.0), ParsaVictor/pcb-component-classifier (MIT),
model weights from Hugging Face. Archives are extracted with path checks (no writing outside data/).
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data"
VISA_TAR = "https://amazon-visual-anomaly.s3.us-west-2.amazonaws.com/VisA_20220922.tar"
VISA_SPLIT = "https://raw.githubusercontent.com/amazon-science/spot-diff/main/split_csv/1cls.csv"
MODELS = ["facebook/dinov2-small", "openai/clip-vit-base-patch16", "Qwen/Qwen2-VL-2B-Instruct",
          "depth-anything/Depth-Anything-V2-Small-hf"]
BIG_VLM = "Qwen/Qwen2.5-VL-7B-Instruct"


def _safe_extract_tar(tar: tarfile.TarFile, dest: Path) -> None:
    dest = dest.resolve()
    for m in tar.getmembers():
        target = (dest / m.name).resolve()
        if not str(target).startswith(str(dest)) or m.issym() or m.islnk():
            raise RuntimeError(f"unsafe archive member: {m.name}")
    tar.extractall(dest)


def _safe_extract_zip(z: zipfile.ZipFile, dest: Path) -> None:
    dest = dest.resolve()
    for n in z.namelist():
        if not str((dest / n).resolve()).startswith(str(dest)):
            raise RuntimeError(f"unsafe archive member: {n}")
    z.extractall(dest)


def _download(url: str, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading {url}\n  -> {out}")
    with urllib.request.urlopen(url) as r, open(out, "wb") as f:
        shutil.copyfileobj(r, f, length=1 << 20)


def visa() -> None:
    root = DATA / "visa"
    if (root / "pcb4" / "Data").is_dir():
        print("VisA already present")
    else:
        tmp = DATA / "raw" / "VisA_20220922.tar"
        if not tmp.exists():
            _download(VISA_TAR, tmp)
        root.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tmp) as t:
            _safe_extract_tar(t, root)
    split = root / "split_csv" / "1cls.csv"
    if not split.exists():
        _download(VISA_SPLIT, split)


def components() -> None:
    from huggingface_hub import hf_hub_download

    for split in ("train", "holdout"):
        dest = DATA / "components" / split
        if dest.exists() and any(dest.rglob("*.png")):
            continue
        z = hf_hub_download("ParsaVictor/pcb-component-classifier", f"{split}.zip", repo_type="dataset")
        with zipfile.ZipFile(z) as zf:
            _safe_extract_zip(zf, dest)
    print("component photos ready (retrain with: python backend/scripts/train_components.py)")


def models(big: bool) -> None:
    from huggingface_hub import snapshot_download

    for repo in MODELS + ([BIG_VLM] if big else []):
        p = snapshot_download(repo, allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "merges.txt", "vocab.json", "tokenizer*", "*.jinja"])
        print("model ready:", repo, p)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mad", action="store_true", help="also print how to get MAD-Sim (manual download)")
    ap.add_argument("--big-vlm", action="store_true", help="also download Qwen2.5-VL-7B (16 GB)")
    ap.add_argument("--skip-visa", action="store_true")
    a = ap.parse_args()
    if not a.skip_visa:
        visa()
    components()
    models(a.big_vlm)
    if a.mad:
        print("MAD-Sim: download from the PAD project (NeurIPS 2023) and place it at data/mad/MAD-Sim/")
    print("done. Start the station:  run.ps1  (Windows)  or  ./run.sh  (Linux / macOS)")


if __name__ == "__main__":
    sys.exit(main())
