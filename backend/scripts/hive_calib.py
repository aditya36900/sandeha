import sys; sys.path.insert(0,".")
import numpy as np, torch
from sandeha.memory import deviation_signature
from sandeha.engine import Session
a=Session("VisA","capsules",seed=0,plant="A"); a.genesis()
b=Session("VisA","capsules",seed=1,plant="B"); b.genesis()
# learn 3 defects at A directly
for s in [x for x in a.eval_pool if x.label==1][:3]:
    g,dist,_=a.mem.inspect([s.image()]); a.learned_defects.append({"label":s.defect_type,"from":"A","vec":deviation_signature(a.mem,g.feats[0][g.fg[0]],dist[0][g.fg[0]])})
fps=a.share_fingerprints(); lib=fps
def sim(img):
    g,dist,_=b.mem.inspect([img]); f=g.feats[0][g.fg[0]]; d=dist[0][g.fg[0]]
    q=deviation_signature(b.mem,f,d)
    return max(float(q@x["vec"].to(q.device)) for x in lib), float(d.max())
used={id(x) for x in a.eval_pool if x.label==1}
ds=[sim(s.image()) for s in [x for x in b.eval_pool if x.label==1][:30]]
gs=[sim(s.image()) for s in [x for x in b.eval_pool if x.label==0][:30]]
print("defect sims", np.round(np.percentile([x[0] for x in ds],[10,50,90]),3), "good sims", np.round(np.percentile([x[0] for x in gs],[10,50,90]),3))
print("defect dmax", np.round(np.percentile([x[1] for x in ds],[10,50,90]),3), "good dmax", np.round(np.percentile([x[1] for x in gs],[10,50,90]),3), "tau_pass", round(b.cal.policy.tau_pass,3))
