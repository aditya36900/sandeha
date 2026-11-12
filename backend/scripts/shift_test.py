import sys; sys.path.insert(0,".")
import numpy as np, torch
from sklearn.metrics import roc_auc_score
from sandeha import data
from sandeha.backbone import Backbone
from sandeha.memory import PatchMemory, loo_scores
from sandeha.shift import PRESETS, ShiftGuard, global_nonconformity, perturb
bb=Backbone.get("facebook/dinov2-small",448)
name, preset = sys.argv[1], sys.argv[2]
p=data.load_visa(name); good,known,ev=p.few_shot(30,5,0)
refs=[s.image() for s in good]; mem=PatchMemory(bb).fit(refs)
gref=bb(refs); calib=global_nonconformity(gref.cls,gref.cls,exclude_self=True).cpu().numpy()
guard=ShiftGuard(calib, loo_scores(mem, refs).cpu().numpy())
used={id(x) for x in good}; pool=[s for s in p.train_good if id(s) not in used]
goods=pool[:85]; defs=[s for s in ev if s.label==1]; test_goods=[s for s in ev if s.label==0]
cond=PRESETS[preset]
def auroc(samples, c=None):
    sc=[];lab=[]
    for i in range(0,len(samples),16):
        b=samples[i:i+16]; ims=[perturb(s.image(),c,seed=i+j) if c else s.image() for j,s in enumerate(b)]
        _,_,x=mem.inspect(ims); sc+=x.tolist(); lab+=[s.label for s in b]
    return roc_auc_score(lab,sc)
stream=[(s,None) for s in goods[:40]]+[(s,cond) for s in goods[40:80]]
alarm_at=None
for t,(s,c) in enumerate(stream):
    im=perturb(s.image(),c,seed=t) if c else s.image()
    g,_,sc=mem.inspect([im]); nc=global_nonconformity(g.cls,gref.cls).item(); h=guard.update(nc, sc.item())
    if h["alarm"] and alarm_at is None: alarm_at=t
print(f"{name}/{preset}: shift starts at part 40 -> alarm at part {alarm_at} (false alarms before shift: {alarm_at is not None and alarm_at<40})")
test=test_goods+defs
a_old=auroc(test); a_shift=auroc(test,cond)
new=[perturb(s.image(),cond,seed=900+i) for i,s in enumerate(goods[80:85])]   # 5 confirmed images under new conditions
mem.add(new)
a_shift_after=auroc(test,cond); a_old_after=auroc(test)
print(f"  AUROC original lighting {a_old:.3f} | under shift {a_shift:.3f} -> after adapting from 5 photos {a_shift_after:.3f} | original after adaptation {a_old_after:.3f} (forgetting check)")
