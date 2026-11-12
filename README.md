# Sandeha v2 — the inspector that knows when it doesn't know

INNOVASIA 2026 · PS-12 *DefectZero Edge: low-data industrial inspection that knows when it is unsure*.

Built entirely on public internet data. Nothing was recorded.

| Dataset | Use | Licence |
|---|---|---|
| **VisA** (Amazon, AWS Open Data) | 12 real products, 1,200 real defects with masks | CC BY 4.0 |
| **MAD-Sim** (PAD, NeurIPS 2023) | 20 objects with camera poses, used for the 3D twin | CC BY-NC-SA 4.0 |

## Run it

Tested on Windows 11, Python 3.12, Node 20+, an RTX 4050 (6 GB). Everything also runs on CPU, more slowly.

```powershell
git clone <this repo> sandeha; cd sandeha
python -m venv .venv
.venv\Scripts\pip install torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cu128
.venv\Scripts\pip install -r requirements.txt

# public datasets + local AI models (~3 GB VisA, ~6 GB models); nothing large is stored in git
.venv\Scripts\python backend\scripts\download_data.py          # add --big-vlm for Qwen2.5-VL-7B (needs ~8 GB GPU)

# dashboard
cd frontend; npm install; npm run build; cd ..

# start the station (serves API + dashboard on one port)
cd backend
..\.venv\Scripts\python -m uvicorn sandeha.api:app --port 8000
```

The repo already contains the trained component-type classifier and the measured results (`data/results/`),
the KiCad 3D models and lighting (`frontend/public/`), and the pitch book (`pitch/Sandeha_Pitch.pdf`).
Not in git: datasets, saved product lines (`data/sessions/`), scanned images (`data/media/`), uploads, and the
station's certificate signing key (`*.pem`, generated on first start).

Then open **http://localhost:8000**.

**Before a demo**, seed two product lines (Bird for the 3D twin, PCB4 with a 50-part production run) so every screen has data. A page refresh never loses them; the dashboard rebuilds from the station.

```powershell
cd backend; ..\.venv\Scripts\python scripts\seed_demo.py
```

**Tests:** `cd backend; ..\.venv\Scripts\python -m pytest -q tests` runs 21 tests in about 5 minutes:

- conformal coverage and the review-budget autopilot,
- shift alarm: no false alarms on clean streams, an alarm on real shifts, quiet under 30% defect bursts,
- every imagined defect type,
- 3D carving,
- certificate tamper detection,
- a full API walkthrough (two-person rule, adaptation never loosening the fail line, page-refresh state),
- the bring-your-own-product flow with the 3D relief, the report, and save/restore,
- station features (HOLD, faults, alerts, roles, trace, analytics, passports),
- live scan: an unlabelled lot leaks no truth, flagged parts get named regions pinned in 3D, grounded explanations, and the blind-spot map. For UI development, run `npm run dev` in `frontend/` and open http://localhost:5173 (it proxies to :8000).

- **AI, all local, no cloud and no API key:** DINOv2-S (anomaly memory), CLIP ViT-B/16 (region names when no labelled examples exist), Qwen2-VL-2B-Instruct (describes defect close-ups and answers free questions), Depth Anything V2 Small (3D relief). Nothing leaves the station. Set `SANDEHA_WARM_AI=0` to skip loading them at startup.
- **Hardware:** a CUDA GPU is used if present. Everything also runs on CPU, just slower.

## Live scan with defects pinned in 3D

**Run the line** opens a tray of **unlabelled** parts straight off the line. The defect mix is drawn at random on the server, and the truth never reaches the browser until you tick *Check against dataset truth*. Scanning a part replays the real pipeline with its real timings:

1. capture and image-quality check,
2. DINOv2 reads the part patch by patch,
3. each patch is compared with its nearest good-patch memory, and the heatmap sweeps in,
4. defect regions are boxed, named and graded,
5. doubt, then decide.

Each defect region is pinned on the 3D twin or relief with a pulsing marker, a leader line and a label card (name, severity, share of the part, measured odds it is real). **What is wrong with it?** returns a cited, fact-built explanation, plus the local VLM's description of each close-up. The VLM describes only; it never decides.

**How accurate are the callouts?** `scripts/region_eval.py` measures them against VisA pixel masks on 380 held-out defective parts (pcb4, capsules, cashew, pcb1), and writes `data/results/regions.json`:

| | |
|---|---|
| callouts that land on the real defect | **75%** |
| defective parts with a callout on the true defect | **90%** |
| strongest callout is the true defect | **82%** |
| callouts per part | 1.4 |
| defect *name* right (from ≤5 labelled examples) | 52% vs 49% majority baseline: shown as a guess |

The keep-rule (a region must reach 70% of the part's hottest spot) raised precision from 44% to 66% on pcb4 at almost no recall cost. We also tried using the 2B VLM to verify regions; it was no better than chance, so it does not vote.

**Blind-spot map (Trust).** It plants scratches of 5 sizes in every cell of the part (the grid covers the part's silhouette, not the photo). Each one is scored exactly like a live part, leave-one-out, and counts as caught only if the heatmap points at it. Misses at the largest size are shown to the VLM: if it cannot see the planted mark either, the cell is *untestable*, not *blind*. An earlier version scored planted defects against a memory that contained the same photo, and painted background cells, which made whole boards look blind.

## Control room (station operations)

The rail has a second group, **Control room**. Every page also has a link: `#overview`, `#pipeline`, `#products`, `#memory`, `#analytics`, `#hardware`, `#history`, `#settings`. Add `?theme=light` for the light theme.

- **Overview:** live KPIs (parts, pass, doubt, fail, hold, review rate, latency, escapes and cost vs a typical AI), decisions per minute, open alerts, product-line cards, latest decisions.
- **Pipeline:** any inspected part walked through 8 stages (see, image check, understand, compare, locate, doubt, decide, learn), with its real intermediate images, numbers and timings.
- **Products:** per line, the calibrated lines, review budget, false-reject guarantee and autopilot (quality manager only). Also a forgetting check and delete.
- **Memory:** good-patch memories, real/imagined/learned defects, half-reviewed parts, and the forgetting chart.
- **Analytics:** defect-type Pareto (rejected, asked, held, escaped vs typical-AI escapes), where flagged parts were unusual, doubt and hold reasons, normal vs changed conditions, timeline.
- **Hardware:** measured CPU, RAM, GPU and latency from this machine; simulated camera, accelerator, conveyor, LED ring and network; fault injection and restore; the outbox to the PLC (Zenoh) and inspectors (Telegram).
- **History:** filter and search every decision, download a CSV, open any part's passport (photo, heatmap, regions, numbers, review, certificate link).
- **Settings:** station name and costs, the four roles and what each may do, the local AI models, station reset, and the audit log.

The **top bar** on every page has:

- an **E-STOP**: anyone can stop the line; releasing a HOLD needs an inspector or above,
- the alerts drawer (acknowledge, resolve, go there),
- the role switcher,
- **Demo mode**: 8 judge scenarios that drive the real engine,
- the theme toggle.

Roles are enforced by the server (`X-Role`); forbidden actions are refused, not just hidden.

## Bring your own product (for organiser-captured parts)

On the landing page, **Bring your own product** takes:

- **Good photos** (at least 8; 20–30 is better).
- **Defect examples** (optional, up to 5).
- **Photos to inspect** (optional).

Sandeha then runs the same genesis, interview and line on your photos. It estimates a **3D relief from a single photo** (Depth Anything V2 Small), and shows defects on that surface.

On the line, **Scan your own photos** accepts more photos at any time. Uploaded photos have no ground truth, so the Arena and risk–coverage numbers count only dataset parts.

## Also built in this round

- **Voice for Ask Sandeha.** Speak a question and hear the answer in English, Hindi or Telugu. This uses the browser's speech service; Chrome sends audio to its servers for recognition.
- **Active learning.** The review queue is ordered by how much each answer would teach: closeness to the decision line, novelty, and difference from parts already answered.
- **Reviewer reliability.** Results of the known-answer checks are shown per reviewer.
- **Persistence.** Product lines save to `data/sessions/` every 90 s and at shutdown. They restore in the background at startup, so the dashboard answers within seconds.
- **Risk–coverage report.** One downloadable HTML page (Trust → *Open the report*), plus a CSV of every decision.
- **ONNX INT8 export** (`backend/scripts/export_onnx.py`). DINOv2-S runs at **21 FPS at 224 px and 8.5 FPS at 336 px** on 4 laptop CPU threads. The model is 24 MB, and INT8 features keep 0.976 cosine similarity to FP32. A Raspberry Pi 5 is not measured.

## Demo flow (7 acts)

1. **Choose a product.** Use a *multi-view* object for the 3D moment and a *VisA* product for the line.
2. **Learn from 30 photos.**
   - The 3D twin is carved live from posed photos (space carving).
   - The AI learns DINOv2 patch memories without training.
   - The Defect Imagination Engine invents 70 defects of 7 kinds.
3. **Answer my questions.** The Curiosity Interview asks about:
   - suspicious "good" photos (training-set poisoning),
   - zones of natural variation,
   - unseen viewpoints,
   - whether it has enough photos,
   - critical zones you paint.
4. **Run the line.** Every verdict comes in plain words, with:
   - the closest precedents and a "what it should look like" counterfactual,
   - defect heat projected onto the 3D twin,
   - the Arena against a typical single-threshold AI, in ₹,
   - the two-person review queue with ghost checks.
5. **Change the conditions.** The Chaos Lab shifts lighting, angle, finish, blur or noise. A conformal test martingale raises the alarm. The AI adapts from 5 photos, then a check proves it didn't forget.
6. **Sign the guarantee.**
   - the trust dial (PPM against human checks against ₹),
   - the live risk–coverage curve,
   - the Blind-Spot Atlas,
   - the measured benchmark on 12 products,
   - Edge Proof,
   - an Ed25519-signed, hash-chained batch certificate with a public QR verification page.
7. **Look ahead.**
   - Defect weather forecast: a simulated wearing tool shows passing parts drifting before failures appear.
   - Hive: a defect learned at Plant A is caught at Plant B using a 384-number fingerprint, with zero pixels shared.
   - Memory Galaxy: a 3D UMAP of everything learned.
   - Ask Sandeha: a grounded copilot in English, Hindi or Telugu.

## Measured results (not claims)

`backend/scripts/p1_eval.py`, VisA, 30 good + 5 defect photos per product, 12 products × 3 seeds, DINOv2-S at 672 px:

| | Defects escaped | Good parts falsely rejected |
|---|---|---|
| Typical single-threshold AI | 39.1% | 3.9% |
| Sandeha (two-threshold calibrated policy + imagined defects) | **14.6%** | 3.9% |

- **Overall:** mean AUROC 0.934, about 2.7× fewer escapes at the same false-reject rate.
- **Review rate:** human review averages 10.2% at a 3% defect rate, right at the PS-12 budget of at most 10%. With the policy aimed at 90% of the budget it was 11.4%, so the 65% aim fixed the overshoot.
- **Shift (capsules, camera bumped):** AUROC fell from 0.964 to 0.70. After adapting from 5 photos it recovered to 0.92. The original conditions stayed at 0.963, so nothing was forgotten.
- **Shift alarm:** fires 10–15 parts after camera, finish or glare shifts on capsules, PCB4 and candle. It never fired on 30%-defect streams (peak evidence 1.3–1.8, against an alarm level of 200).
- **Review-budget autopilot:** on a live PCB4 line with 15% defects, review fell from about 40% to 11%. It escaped 1 of 10 defects, against 3 for the typical AI.
- **Contamination check:** a defective part planted in the 30 "good" photos was flagged on capsules (31σ) and candle (7σ). It was missed on PCB1, where the defect is subtle.
- **Edge Proof** (laptop CPU, 4 threads, no GPU): INT8 at 224 px runs at 9.1 FPS. At 448 px it runs at 2.1 FPS. The Pi 5 was not measured.

## Known limitations

- **Multi-view inspection is weak.** On MAD-Sim, AUROC is 0.58–0.76, in line with published PatchCore results. Use MAD for the 3D twin and VisA for the line.
- **The promised escape rate is only an estimate.** It is computed from imagined defects and is poorly calibrated per product (too pessimistic on capsules, too optimistic on macaroni). The UI labels it as an estimate, and the live measured curve is the ground truth.
- **The shift alarm's false-alarm rate is empirical.** It uses a 70th-percentile filter over 9 parts, so the exact Ville bound no longer holds.
- **A dirty lens is not caught by the shift alarm.** Only severe blur is caught, by the image-quality check.
- **The review-budget autopilot trades a little escape risk for staying within budget.** It raises the pass line, never the fail line, and the gauge shows the line in use.
- **Hive matching is narrow.** It works for recurring defect types. Separation between defect and good fingerprints is modest (median similarity 0.21 against 0.14).
- **Saved sessions are large.** Each product line takes about 100–160 MB on disk (mostly the patch memory at fp16 and the 3D twin).
- **The single-photo relief is relative depth from one image.** It is a visual aid, not a measurement.
