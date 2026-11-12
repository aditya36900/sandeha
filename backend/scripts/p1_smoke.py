import sys, time, torch, numpy as np
sys.path.insert(0, ".")
from sklearn.metrics import roc_auc_score
from sandeha import data
from sandeha.backbone import Backbone
from sandeha.memory import PatchMemory
src, cats = sys.argv[1], sys.argv[2].split(",")
model = sys.argv[3] if len(sys.argv) > 3 else "facebook/dinov2-small"
res = int(sys.argv[4]) if len(sys.argv) > 4 else 448
bb = Backbone.get(model, res)
for c in cats:
    p = data.load(src, c)
    good, known, ev = p.few_shot(30, 5, seed=0)
    t = time.time()
    mem = PatchMemory(bb).fit([s.image() for s in good])
    tfit = time.time() - t
    scores, labels = [], []
    t = time.time()
    for i in range(0, len(ev), 16):
        b = ev[i:i+16]
        _, _, sc = mem.inspect([s.image() for s in b])
        scores += sc.tolist(); labels += [s.label for s in b]
    dt = (time.time() - t) / len(ev)
    print(f"{src}/{c}: AUROC={roc_auc_score(labels, scores):.3f}  n={len(ev)} defects={sum(labels)} bank={len(mem.bank)} fit={tfit:.1f}s  {1/dt:.1f} img/s", flush=True)
