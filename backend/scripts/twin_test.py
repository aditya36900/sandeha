import sys, time, numpy as np, torch
sys.path.insert(0, ".")
from PIL import Image
from sandeha import data
from sandeha.twin import Twin, load_view
p = data.load_mad(sys.argv[1] if len(sys.argv) > 1 else "01Gorilla")
rng = np.random.default_rng(0); idx = rng.choice(len(p.train_good), 30, replace=False)
views = [load_view(p.train_good[i].path, p.train_good[i].pose, p.fov_x) for i in idx]
# bounds check: camera distance
print("cam dist", np.linalg.norm(views[0].c2w[:3,3]).round(2))
tw = Twin(128, 1.0); t = time.time(); trace = []
for v in views: trace.append(tw.carve(v))
torch.cuda.synchronize(); print("carve 30 views s", round(time.time()-t, 3), "occupied trace", trace[:3], "...", trace[-1])
t = time.time(); ex = tw.export(); print("export s", round(time.time()-t,2), "surface pts", ex["count"], "seen", round(ex["seen"],3))
pos = np.array(ex["positions"]).reshape(-1,3); print("bbox", pos.min(0).round(2), pos.max(0).round(2))
# re-render from a held-out view to verify
hv = load_view(p.train_good[int(set(range(len(p.train_good))).difference(idx).pop())].path, p.train_good[0].pose, p.fov_x)
test = p.train_good[[i for i in range(len(p.train_good)) if i not in set(idx)][5]]
hv = load_view(test.path, test.pose, p.fov_x)
u, v, z, _ = Twin.project(torch.tensor(pos, dtype=torch.float32, device="cuda"), hv.c2w, hv.fov_x, (400, 400))
img = np.full((400,400,3), 255, np.uint8); col = (np.array(ex["colors"]).reshape(-1,3)*255).astype(np.uint8)
order = torch.argsort(z, descending=True).cpu().numpy(); u=u.cpu().numpy(); v=v.cpu().numpy()
for i in order:
    x, y = int(u[i]), int(v[i])
    if 0 <= x < 399 and 0 <= y < 399: img[y:y+2, x:x+2] = col[i]
Image.fromarray(np.concatenate([hv.image, img], 1)).save(r"C:/Users/HP/AppData/Local/Temp/claude/3b0f56b69c14897f/8f1aeb14-7910-4131-8747-07096791f054/scratchpad/twin_check.png")
print("cov", round(tw.coverage()["covered"],3))
