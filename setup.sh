#!/usr/bin/env bash
# One-command setup for Sandeha on Linux / macOS.
#   ./setup.sh               # everything
#   ./setup.sh --cpu         # force CPU PyTorch
#   ./setup.sh --skip-data   # skip the ~9 GB of datasets and models
#   ./setup.sh --big-vlm     # also Qwen2.5-VL-7B (16 GB, NVIDIA GPU with ~8 GB free)
#   ./setup.sh --no-extras   # skip optional packages
set -euo pipefail
cd "$(dirname "$0")"
CPU=0; SKIP=0; BIG=0; NOEXTRA=0
for a in "$@"; do case "$a" in
  --cpu) CPU=1;; --skip-data) SKIP=1;; --big-vlm) BIG=1;; --no-extras) NOEXTRA=1;;
  *) echo "unknown option $a"; exit 1;; esac; done
step() { printf '\n==> %s\n' "$1"; }
fail() { echo "ERROR: $1" >&2; exit 1; }

step "Checking Python (3.10 to 3.13, 3.12 recommended)"
PY=""
for c in python3.12 python3.11 python3.13 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)'; then PY="$c"; break; fi
done
[ -n "$PY" ] || fail "Python 3.10-3.13 not found (install python3.12)"
echo "using $PY ($($PY --version))"

step "Checking Node.js (18 or newer)"
command -v node >/dev/null || fail "Node.js not found: install the LTS from https://nodejs.org/"
NODE_MAJOR=$(node -p 'process.versions.node.split(".")[0]'); [ "$NODE_MAJOR" -ge 18 ] || fail "Node $(node --version) too old"

step "Creating the virtual environment (.venv)"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
VPY=.venv/bin/python
"$VPY" -m pip install --upgrade pip --quiet

step "Installing PyTorch"
if [ "$CPU" -eq 0 ] && command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  echo "NVIDIA GPU found: CUDA 12.8 build"
  "$VPY" -m pip install torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cu128
elif [ "$(uname)" = "Darwin" ]; then
  echo "macOS: default build (Apple GPU via MPS where supported)"
  "$VPY" -m pip install torch==2.11.0 torchvision==0.26.0
else
  echo "no NVIDIA GPU (or --cpu): CPU build"
  "$VPY" -m pip install torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cpu
fi

step "Installing Python packages"
"$VPY" -m pip install -r requirements.txt
[ "$NOEXTRA" -eq 1 ] || "$VPY" -m pip install -r requirements-extra.txt || echo "optional extras failed; the station still runs"

if [ "$SKIP" -eq 0 ]; then
  step "Downloading public datasets and local AI models (one time, ~9 GB)"
  if [ "$BIG" -eq 1 ]; then "$VPY" backend/scripts/download_data.py --big-vlm; else "$VPY" backend/scripts/download_data.py; fi
else echo "skipping data (later: .venv/bin/python backend/scripts/download_data.py)"; fi

step "Building the dashboard"
( cd frontend && { [ -f package-lock.json ] && npm ci || npm install; } && npm run build )

step "Checking the install"
"$VPY" backend/scripts/check_install.py || true
echo; echo "Done. Start the station with: ./run.sh   (or ./run.sh --dev for hot reload)"
