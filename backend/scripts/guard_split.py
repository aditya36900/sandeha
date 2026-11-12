import sys; sys.path.insert(0,".")
import numpy as np
from sandeha.engine import Session
for name in sys.argv[1].split(","):
    s=Session("VisA",name,seed=0); s.genesis()
    out=[]
    for label, pool in [("train-split goods", s.spare_good[:50]), ("test-split goods", [x for x in s.eval_pool if x.label==0][:50]), ("test defects", [x for x in s.eval_pool if x.label==1][:30])]:
        s.guard.reset(); ps=[]
        for x in pool:
            s.inspect(x.image(), truth=x.label); ps.append(s.guard.history[-1]["p"])
        out.append(f"{label}: median p {np.median(ps):.2f}, alarm {s.guard.alarmed}, max evidence {max(h['martingale'] for h in s.guard.history):.1f}")
    print(name, " | ".join(out), flush=True)
