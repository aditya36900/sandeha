#!/usr/bin/env bash
# Start the Sandeha station on Linux / macOS.
#   ./run.sh            # station + built dashboard on http://localhost:8000
#   ./run.sh --dev      # also Vite with hot reload on http://localhost:5173
#   ./run.sh --seed     # seed two demo product lines after start
#   PORT=8080 ./run.sh
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8000}"
[ -x .venv/bin/python ] || { echo "No .venv: run ./setup.sh first"; exit 1; }
for a in "$@"; do case "$a" in
  --dev) ( cd frontend && SANDEHA_API="http://127.0.0.1:$PORT" npm run dev ) & echo "Vite on http://localhost:5173";;
  --seed) ( sleep 5; .venv/bin/python backend/scripts/seed_demo.py ) & echo "seeding demo lines in the background";;
  *) echo "unknown option $a"; exit 1;; esac; done
echo "Sandeha station on http://localhost:$PORT (Ctrl+C to stop)"
cd backend && exec ../.venv/bin/python -m uvicorn sandeha.api:app --host 127.0.0.1 --port "$PORT"
