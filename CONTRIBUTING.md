# Working on Sandeha

## 1. Get running (once)

| | Windows (PowerShell) | Linux / macOS |
|---|---|---|
| Prerequisites | Python 3.12, Node 18+ (LTS), Git; an NVIDIA GPU is optional | same |
| Setup | `powershell -ExecutionPolicy Bypass -File .\setup.ps1` | `./setup.sh` |
| Check | `.venv\Scripts\python backend\scripts\check_install.py` | `.venv/bin/python backend/scripts/check_install.py` |
| Run | `.\run.ps1` → http://localhost:8000 | `./run.sh` |
| Run with hot reload | `.\run.ps1 -Dev` → edit `frontend/src`, see it on http://localhost:5173 | `./run.sh --dev` |
| Demo data | `.\run.ps1 -Seed` (learns pcb3 + pcb4 and scans a production run) | `./run.sh --seed` |

Setup downloads about 9 GB once (VisA ~3 GB, models ~6 GB) into `data/` and the Hugging Face cache. Options:
`-Cpu` / `--cpu`, `-SkipData` / `--skip-data`, `-BigVlm` / `--big-vlm` (Qwen2.5-VL-7B, 16 GB, needs ~8 GB GPU), `-NoExtras` / `--no-extras`.

First start: open http://localhost:8000, pick a circuit board (pcb4 is the best demo), and wait about a minute
while it learns 30 good boards and maps the components (then "Recalibrated on the board only" appears).

## 2. Where things live

```
backend/sandeha/
  api.py            FastAPI app: product lines, scan, explain, board, x-ray, approval, chips, uploads, websocket events
  api_station.py    station routes: HOLD, faults, alerts, roles (X-Role header), analytics, history, settings, demo scenarios
  engine.py         Session = one product line: learn (genesis), calibrate, inspect, adapt, review, board-only scoring
  memory.py         DINOv2 patch memory: nearest good patch for every patch, image score
  trust.py          split-conformal two-line policy (pass / doubt / fail) and the review-budget autopilot
  shift.py          conformal martingale that notices changed lighting or a bumped camera
  board.py          electronics: golden board, component segmentation + typing, per-component diagnosis, X-ray layers
  smt.py            SMT line context: root causes, IPC-A-610 grading, DPMO / FPY / false calls, SPC, rework, materials
  approval.py       approval-desk dossier (case for / against, risk, what would change it) and the VLM's view
  chips.py          chip identity: read IC markings with the VLM, compare with the golden board
  regions.py        heatmap -> named, measured defect regions (+ measured odds a region is real)
  vlm.py            local vision-language model (Qwen2-VL-2B; Qwen2.5-VL-7B when it fits), loads on demand
  copilot.py        "Ask Sandeha": grounded answers from the evidence
  imagine.py        synthetic defects used to place the pass line (and the blind-spot map)
  persist.py        saves / restores product lines in data/sessions/
backend/scripts/    evaluations (p1_eval, region_eval, board_eval, flag_precision, board_only_eval), training, download, seeding
backend/tests/      pytest (conftest sets SANDEHA_PERSIST=0 so tests never touch your saved lines)
frontend/src/
  acts/             the journey screens: Choose, Genesis (learn), Interview, Line (scan), Chaos, Trust, Beyond
  line/             electronics pages: Approval, SmtLine, Quality, Spc, Rework, Materials, Bom, XRay
  room/             control room: Overview, Pipeline, Products, Memory, Analytics, Hardware, History, Settings
  ui/               LiveScan, Board3D (3D board + info panel), Twin3D, FaultLab, FlowBar, TopBar, BoardViews…
  api.ts            every backend call + types       store.tsx   app state, roles, events, toasts, page routing (#hash)
data/results/       measured numbers (JSON) and the trained component classifier (component_clf.pkl) — in git
pitch/              pitch book PDF + its HTML source
```

## 3. Daily loop

```powershell
git pull
.\run.ps1 -Dev                                   # backend on :8000, Vite with hot reload on :5173
.venv\Scripts\python -m pytest -q backend\tests  # ~7 min on a GPU (learns real product lines)
cd frontend; npx tsc --noEmit                    # type check
```

Backend changes need a restart of `run.ps1` (the station restores saved lines in about a minute).
Frontend changes appear instantly on :5173; `npm run build` refreshes what :8000 serves.

## 4. Settings (environment variables)

| Variable | Default | Effect |
|---|---|---|
| `SANDEHA_PERSIST` | `1` | `0` = do not save or restore product lines (tests use this) |
| `SANDEHA_WARM_AI` | `1` | `0` = do not pre-load CLIP at start |
| `SANDEHA_API` | `http://127.0.0.1:8000` | where the Vite dev server proxies API calls |

## 5. House rules

1. **Measure before you claim.** Every number shown in the UI or the pitch comes from a script in `backend/scripts`.
   If you change detection logic, re-run the matching evaluation and update `data/results/` and the README.
2. **Label anything simulated.** Feeder, moisture-clock and reflow data are simulated and say so on screen. Keep it that way.
3. **Show limits next to the feature.** If something is weak (dry joints, dense boards, defect names), the UI says it.
4. **Never commit secrets or big data.** `*.pem`, `data/sessions`, `data/media`, datasets and models are git-ignored.
5. **Branch, then pull request.** `git checkout -b feature/short-name`; keep `main` demo-ready; run the tests first.

## 6. Common problems

| Symptom | Fix |
|---|---|
| `check_install` says a model or VisA is missing | `python backend/scripts/download_data.py` (re-run is safe, finished parts are kept) |
| CUDA out of memory / scans slow | close other GPU apps; the 7B VLM only loads when ~5.6 GB of GPU memory is free |
| Dashboard blank at :8000 | `cd frontend; npm run build` |
| Old screens after an update | hard reload: Ctrl+Shift+R |
| First scan of a new line takes ~1 min | it is learning the board and calibrating; watch the toasts |
| PowerShell refuses to run scripts | `powershell -ExecutionPolicy Bypass -File .\setup.ps1` |
