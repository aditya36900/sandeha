"""Is this machine ready to run Sandeha? Prints what is present, what is missing, and the command that fixes it.

  python backend/scripts/check_install.py
Exit code 0 when everything needed to run is present (optional items only warn).
"""
from __future__ import annotations

import importlib
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
OK, WARN, BAD = "OK  ", "WARN", "MISS"
rows: list[tuple[str, str, str, str]] = []
critical = False


def row(state: str, what: str, detail: str = "", fix: str = "") -> None:
    global critical
    rows.append((state, what, detail, fix))
    if state == BAD:
        critical = True


def main() -> int:
    v = sys.version_info
    row(OK if (3, 10) <= v[:2] <= (3, 13) else BAD, "Python", f"{platform.python_version()}", "install Python 3.12")
    for mod, pip in (("fastapi", "fastapi"), ("uvicorn", "uvicorn"), ("transformers", "transformers"), ("cv2", "opencv-python-headless"),
                     ("sklearn", "scikit-learn"), ("umap", "umap-learn"), ("cryptography", "cryptography"), ("qrcode", "qrcode"),
                     ("psutil", "psutil"), ("onnxruntime", "onnxruntime")):
        try:
            importlib.import_module(mod)
            row(OK, f"package {pip}")
        except Exception as e:
            row(BAD, f"package {pip}", type(e).__name__, "pip install -r requirements.txt")
    try:
        import torch

        cuda = torch.cuda.is_available()
        if cuda:
            free, total = torch.cuda.mem_get_info()
            row(OK, "PyTorch + GPU", f"{torch.__version__} | {torch.cuda.get_device_name(0)} | {total / 2**30:.1f} GB ({free / 2**30:.1f} free)")
            if total / 2**30 < 7.5:
                row(WARN, "Qwen2.5-VL-7B", "GPU under 8 GB: the station uses Qwen2-VL-2B instead (automatic)")
        else:
            row(WARN, "PyTorch (CPU only)", torch.__version__, "works, slower; for CUDA re-run setup on a machine with an NVIDIA driver")
    except Exception as e:
        row(BAD, "PyTorch", type(e).__name__, "re-run setup.ps1 / setup.sh")
    for mod, why in (("bitsandbytes", "4-bit 7B VLM"), ("accelerate", "4-bit 7B VLM"), ("cascadio", "STEP -> GLB conversion")):
        try:
            importlib.import_module(mod)
            row(OK, f"extra {mod}", why)
        except Exception:
            row(WARN, f"extra {mod}", f"optional ({why})", "pip install -r requirements-extra.txt")
    visa = DATA / "visa"
    pcbs = [p for p in ("pcb1", "pcb2", "pcb3", "pcb4") if (visa / p / "Data").is_dir()]
    row(OK if pcbs else BAD, "VisA dataset", ", ".join(pcbs) or "not found", "python backend/scripts/download_data.py")
    row(OK if (visa / "split_csv" / "1cls.csv").exists() else BAD, "VisA split file", "", "python backend/scripts/download_data.py")
    comp = DATA / "components" / "train"
    row(OK if comp.exists() and any(comp.rglob("*.png")) else WARN, "component photos", "only needed to retrain the classifier",
        "python backend/scripts/download_data.py")
    row(OK if (DATA / "results" / "component_clf.pkl").exists() else BAD, "component classifier", "data/results/component_clf.pkl",
        "python backend/scripts/train_components.py")
    try:
        from huggingface_hub import try_to_load_from_cache

        for repo, need in (("facebook/dinov2-small", True), ("openai/clip-vit-base-patch16", True),
                           ("Qwen/Qwen2-VL-2B-Instruct", False), ("depth-anything/Depth-Anything-V2-Small-hf", False),
                           ("Qwen/Qwen2.5-VL-7B-Instruct", False)):
            hit = try_to_load_from_cache(repo, "config.json")
            row(OK if isinstance(hit, str) else (BAD if need else WARN), f"model {repo}", "" if isinstance(hit, str) else
                ("needed" if need else "optional: downloads on first use"), "python backend/scripts/download_data.py")
    except Exception as e:
        row(WARN, "model cache", type(e).__name__)
    dist = ROOT / "frontend" / "dist" / "index.html"
    row(OK if dist.exists() else BAD, "dashboard build", "frontend/dist", "cd frontend && npm install && npm run build")
    w = max(len(r[1]) for r in rows)
    for st, what, detail, fix in rows:
        line = f"[{st}] {what.ljust(w)}  {detail}"
        if st != OK and fix:
            line += f"\n        fix: {fix}"
        print(line)
    print("\nREADY - start with run.ps1 (Windows) or ./run.sh" if not critical else "\nNOT READY - fix the MISS lines above")
    return 1 if critical else 0


if __name__ == "__main__":
    sys.exit(main())
