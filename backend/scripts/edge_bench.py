"""Edge Proof: measure CPU-only inference speed (no GPU) with 4 threads, like a Raspberry Pi 5 (4 cores).
Writes data/results/edge.json. Pi numbers are NOT measured here; see the 'note' field."""
import json, sys, time
from pathlib import Path
sys.path.insert(0, ".")
import torch
torch.set_num_threads(4)
from transformers import AutoModel
from PIL import Image
import numpy as np
from sandeha import data
m = AutoModel.from_pretrained("facebook/dinov2-small").eval()
params = sum(p.numel() for p in m.parameters())
q = torch.ao.quantization.quantize_dynamic(m, {torch.nn.Linear}, dtype=torch.qint8)
img = data.load_visa("pcb4").train_good[0].image()
rows = []
for name, model in [("fp32", m), ("int8-dynamic", q)]:
    for res in (224, 336, 448):
        x = torch.from_numpy(np.asarray(img.resize((res, res)), dtype=np.float32) / 255).permute(2, 0, 1)[None]
        x = (x - torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)) / torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)
        bank = torch.nn.functional.normalize(torch.randn(20000, 384), dim=-1)
        with torch.no_grad():
            for _ in range(2): model(pixel_values=x)
            t = time.perf_counter(); n = 6
            for _ in range(n):
                f = torch.nn.functional.normalize(model(pixel_values=x).last_hidden_state[0, 1:], dim=-1)
                (f @ bank.T).max(1)
            dt = (time.perf_counter() - t) / n
        rows.append({"precision": name, "resolution": res, "fps": round(1 / dt, 2), "msPerPart": round(1000 * dt, 1)})
        print(rows[-1], flush=True)
out = {"measured": True, "device": "laptop CPU, 4 threads (no GPU)", "params": params,
       "sizeMBfp32": round(params * 4 / 1e6, 1), "sizeMBint8": round(params / 1e6, 1), "rows": rows,
       "note": "Measured on this laptop's CPU limited to 4 threads. A Raspberry Pi 5 CPU is slower; validate on the device. "
               "On Pi 5 + Hailo-8L the backbone would run on the NPU after compilation (not done here)."}
Path("../data/results").mkdir(parents=True, exist_ok=True)
Path("../data/results/edge.json").write_text(json.dumps(out, indent=1))
