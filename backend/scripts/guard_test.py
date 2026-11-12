import sys; sys.path.insert(0,".")
import numpy as np
from sandeha.engine import Session
from sandeha.shift import PRESETS
for name in sys.argv[1].split(","):
    s=Session("VisA",name,seed=0); s.genesis(); rng=np.random.default_rng(3)
    for i in range(60):
        x=s.next_sample(0.3,rng); s.inspect(x.image(),truth=x.label)
    fa = s.guard.alarmed; m = max(h["martingale"] for h in s.guard.history)
    res=[]
    for pr in ["camera_bumped","new_surface_finish","night_shift_lights","dirty_lens","skylight_glare"]:
        s.guard.reset(); s.set_conditions(PRESETS[pr].__dict__); at=None
        for i in range(40):
            x=s.next_sample(0.0,rng); s.inspect(x.image(),truth=x.label)
            if s.guard.alarmed and at is None: at=i+1
        res.append(f"{pr}: alarm after {at} parts")
        s.set_conditions({})
    print(f"{name}: 60 normal parts at 30% defects -> false alarm: {fa} (max evidence {m:.1f}) | " + " | ".join(res), flush=True)
