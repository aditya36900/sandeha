"""Edge deployment: export the DINOv2-S backbone to ONNX, quantise to INT8, and measure with ONNX Runtime
on 4 CPU threads (Raspberry Pi 5 has 4 cores). Also checks that INT8 features match FP32 features.
Results are merged into data/results/edge.json (shown on the Trust page)."""
import json
import sys
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch
from onnxruntime.quantization import QuantType, quantize_dynamic
from transformers import AutoModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sandeha import data  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "data" / "edge"
OUT.mkdir(parents=True, exist_ok=True)


class Patches(torch.nn.Module):
    def __init__(self, m):
        super().__init__()
        self.m = m

    def forward(self, x):
        h = self.m(pixel_values=x).last_hidden_state
        return torch.nn.functional.normalize(h[:, 1:], dim=-1)


model = Patches(AutoModel.from_pretrained("facebook/dinov2-small").eval())
img = data.load_visa("pcb4").train_good[0].image()
rows, sims = [], {}
for res in (224, 336):
    fp32, int8 = OUT / f"dinov2s_{res}.onnx", OUT / f"dinov2s_{res}_int8.onnx"
    x = torch.from_numpy(np.asarray(img.resize((res, res)), np.float32) / 255).permute(2, 0, 1)[None]
    x = (x - torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)) / torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)
    torch.onnx.export(model, (x,), str(fp32), input_names=["image"], output_names=["patches"], opset_version=17, dynamo=False)
    quantize_dynamic(str(fp32), str(int8), weight_type=QuantType.QInt8)
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 4
    outs = {}
    for name, path in (("onnx-fp32", fp32), ("onnx-int8", int8)):
        sess = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
        feed = {"image": x.numpy()}
        for _ in range(2):
            sess.run(None, feed)
        t = time.perf_counter()
        n = 8
        for _ in range(n):
            out = sess.run(None, feed)[0]
        dt = (time.perf_counter() - t) / n
        outs[name] = out[0]
        rows.append({"precision": name, "resolution": res, "fps": round(1 / dt, 2), "msPerPart": round(1000 * dt, 1),
                     "sizeMB": round(path.stat().st_size / 1e6, 1)})
        print(rows[-1], flush=True)
    sims[res] = float((outs["onnx-fp32"] * outs["onnx-int8"]).sum(-1).mean())
    print(f"res {res}: mean cosine similarity INT8 vs FP32 patch features = {sims[res]:.4f}", flush=True)

edge_path = Path(__file__).resolve().parents[2] / "data" / "results" / "edge.json"
edge = json.loads(edge_path.read_text()) if edge_path.exists() else {"measured": True, "rows": []}
edge["rows"] = [r for r in edge.get("rows", []) if not r["precision"].startswith("onnx")] + rows
edge["onnxFeatureSimilarity"] = sims
edge["note"] = ("Measured on this laptop's CPU limited to 4 threads (PyTorch and ONNX Runtime). A Raspberry Pi 5 CPU is "
                "slower; validate on the device. ONNX INT8 patch features keep cosine similarity "
                + ", ".join(f"{v:.3f} at {k}px" for k, v in sims.items()) + " with FP32.")
edge_path.write_text(json.dumps(edge, indent=1))
print("written", edge_path)
