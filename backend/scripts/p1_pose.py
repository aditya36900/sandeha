import sys, time, torch, numpy as np
sys.path.insert(0, ".")
from sklearn.metrics import roc_auc_score
from sandeha import data
from sandeha.backbone import Backbone
bb = Backbone.get("facebook/dinov2-small", 448)
def fps(points, k):
    sel=[0]; d=np.linalg.norm(points-points[0],axis=1)
    for _ in range(k-1):
        i=int(d.argmax()); sel.append(i); d=np.minimum(d,np.linalg.norm(points-points[i],axis=1))
    return sel
for c in sys.argv[1].split(","):
    p = data.load("mad", c)
    cams = np.stack([s.pose[:3,3] for s in p.train_good])
    for mode in ["random+all", "spread+all", "spread+retrieve5", "spread+retrieve3"]:
        if mode.startswith("random"):
            good, _, ev = p.few_shot(30, 5, 0)
        else:
            idx = fps(cams, 30); good = [p.train_good[i] for i in idx]; _, _, ev = p.few_shot(30, 5, 0)
        g = bb([s.image() for s in good])
        ref_f, ref_fg, ref_cls = g.feats, g.fg, g.cls
        scores, labels = [], []
        for i in range(0, len(ev), 16):
            b = ev[i:i+16]; q = bb([s.image() for s in b])
            for j in range(len(b)):
                if "retrieve" in mode:
                    k = int(mode[-1]); nn = (q.cls[j] @ ref_cls.T).topk(k).indices
                else:
                    nn = torch.arange(len(good), device=ref_f.device)
                bank = ref_f[nn][ref_fg[nn]]
                d = 1 - (q.feats[j] @ bank.T).max(1).values
                d = d.masked_fill(~q.fg[j], 0)
                scores.append(d.topk(max(1, int(0.01*d.numel()))).values.mean().item()); labels.append(b[j].label)
        print(f"{c} {mode:18s} AUROC={roc_auc_score(labels, scores):.3f}", flush=True)
