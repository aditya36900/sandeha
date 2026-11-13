"""Build the live-demo photo kit: real PCB photos you can upload from the computer, per board type.

demo_kit/<board>/
    1_good_references_30/   30 good boards       -> "Good parts" box (the ONLY thing the station learns from)
    2_known_defects_5/      5 known defects      -> "Defect examples" box (tunes strictness; optional)
    3_boards_to_inspect/    16 unlabelled boards -> upload in Live scan; neutral names, nobody can read the answer
    answers.csv             the truth for the presenter (which board is defective and how)

The folders use the same references a built-in line uses (seed 0), and the boards to inspect are never among the
references or the known defects. All photos: VisA dataset (Amazon), CC BY 4.0.

usage: python scripts/make_demo_kit.py [pcb1 pcb2 pcb3 pcb4]
"""
from __future__ import annotations

import csv
import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

from sandeha import data  # noqa: E402

KIT = Path(__file__).resolve().parents[2] / "demo_kit"
TITLE = {"pcb1": "Ultrasonic sensor (front)", "pcb2": "Ultrasonic sensor (back)", "pcb3": "IR sensor module",
         "pcb4": "Li-ion charger board"}
N_GOOD, N_BAD = 8, 8


def save(sample, dst: Path) -> None:
    im = sample.image()
    if max(im.size) > 1280:  # quick to upload, same content
        im.thumbnail((1280, 1280), Image.LANCZOS)
    im.save(dst, quality=92)


def build(name: str) -> None:
    prod = data.load("VisA", name)
    good, known, ev = prod.few_shot(30, 5, 0)
    root = KIT / name
    if root.exists():
        shutil.rmtree(root)
    for d in ("1_good_references_30", "2_known_defects_5", "3_boards_to_inspect"):
        (root / d).mkdir(parents=True)
    for i, s in enumerate(good):
        save(s, root / "1_good_references_30" / f"good_{i + 1:02d}.jpg")
    for i, s in enumerate(known):
        save(s, root / "2_known_defects_5" / f"defect_{i + 1:02d}.jpg")
    rng = random.Random(7)
    goods = [s for s in ev if s.label == 0]
    bads = [s for s in ev if s.label == 1]
    rng.shuffle(goods)
    rng.shuffle(bads)
    by_type, pick_bad = {}, []
    for s in bads:  # as many different defect types as possible
        by_type.setdefault(s.defect_type.split(",")[0].strip(), []).append(s)
    while len(pick_bad) < N_BAD and any(by_type.values()):
        for t in sorted(by_type):
            if by_type[t] and len(pick_bad) < N_BAD:
                pick_bad.append(by_type[t].pop())
    mix = [(s, 0) for s in goods[:N_GOOD]] + [(s, 1) for s in pick_bad]
    rng.shuffle(mix)
    with open(root / "answers.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file", "truth", "defect"])
        for i, (s, lab) in enumerate(mix):
            fn = f"board_{i + 1:02d}.jpg"
            save(s, root / "3_boards_to_inspect" / fn)
            w.writerow([fn, "DEFECTIVE" if lab else "good", s.defect_type if lab else ""])
    print(name, "kit ready:", root)


README = """SANDEHA LIVE DEMO KIT
=====================
Real photos of four circuit boards (VisA dataset, Amazon, CC BY 4.0). Pick any board; the steps are the same.

  pcb1  Ultrasonic sensor (front)      pcb3  IR sensor module
  pcb2  Ultrasonic sensor (back)       pcb4  Li-ion charger board

A. TEACH A BOARD FROM NOTHING (about a minute)
   1. Open the app, go to "Choose a board", scroll to "Bring your own product".
   2. Drop the 30 photos from  1_good_references_30  into "Good parts".
   3. (optional) Drop  2_known_defects_5  into "Defect examples".
   4. Press "Learn this product". No training happens: it only remembers what good looks like.

B. INSPECT PHOTOS FROM THE COMPUTER
   1. Go to "Scan boards", switch the Live scan panel to "Upload".
   2. Drop the photos from  3_boards_to_inspect  (names are neutral: board_01.jpg ...).
   3. Click any photo, or "Scan all". The verdict, heat map, component faults and 3D view appear for each.
   4. Check the station against  answers.csv  (the truth: which boards are defective and how).

The boards in folder 3 are never among the references or the known defects.
The same folder 3 also works on the built-in line of that board (no teaching step needed).
"""

if __name__ == "__main__":
    for nm in sys.argv[1:] or ["pcb1", "pcb2", "pcb3", "pcb4"]:
        build(nm)
    (KIT / "README.txt").write_text(README)
    print("wrote", KIT / "README.txt")
