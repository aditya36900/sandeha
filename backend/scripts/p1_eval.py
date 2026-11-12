"""PS-12 protocol evaluation on VisA: 30 good + 5 defects per product, rest is the test stream."""
import json, sys, time
from pathlib import Path
import numpy as np
sys.path.insert(0, ".")
from sklearn.metrics import roc_auc_score
from sandeha import data
from sandeha.backbone import Backbone
from sandeha.memory import PatchMemory, loo_scores
from sandeha.imagine import imagine_set
from sandeha.trust import Calibrator, conformal_upper, outcome_stats, random_abstention, risk_coverage

model = sys.argv[1] if len(sys.argv) > 1 else "facebook/dinov2-small"
res = int(sys.argv[2]) if len(sys.argv) > 2 else 448
seeds = [int(s) for s in (sys.argv[3] if len(sys.argv) > 3 else "0,1,2").split(",")]
cats = sys.argv[4].split(",") if len(sys.argv) > 4 else data.visa_categories()
bb = Backbone.get(model, res)
rows = []
out = Path("../data/results"); out.mkdir(parents=True, exist_ok=True)
for c in cats:
    p = data.load_visa(c)
    for seed in seeds:
        good, known, ev = p.few_shot(30, 5, seed)
        refs = [s.image() for s in good]
        mem = PatchMemory(bb).fit(refs)
        g_loo = loo_scores(mem, refs).cpu().numpy()
        _, _, d_sc = mem.inspect([s.image() for s in known])
        real_d = d_sc.cpu().numpy()
        # Defect Imagination Engine: 60 synthetic defects on the references (masks from the backbone)
        gref = bb(refs); fgs = [f.reshape(gref.hw).cpu().numpy() for f in gref.fg]
        imag = imagine_set(refs, 60, np.random.default_rng(seed), sizes=(0.03, 0.10), masks=None)
        syn_sc = np.concatenate([mem.inspect([x.image for x in imag[i:i+16]])[2].cpu().numpy() for i in range(0, 60, 16)])
        cal = Calibrator(g_loo, np.concatenate([real_d, syn_sc]), alpha_fr=0.02, beta=0.05, budget=0.10)
        cal_real_only = Calibrator(g_loo, real_d, alpha_fr=0.02, beta=0.05, budget=0.10, spend_budget=False)
        scores, labels = [], []
        for i in range(0, len(ev), 16):
            b = ev[i:i + 16]
            _, _, sc = mem.inspect([s.image() for s in b])
            scores += sc.tolist(); labels += [s.label for s in b]
        scores, labels = np.array(scores), np.array(labels)
        pol = cal.policy
        ours = outcome_stats(scores, labels, pol.tau_pass, pol.tau_fail)
        tau95 = conformal_upper(g_loo, 0.05)  # typical single-threshold system
        base = outcome_stats(scores, labels, tau95, tau95)
        rc = risk_coverage(scores, labels, pol.tau_fail)
        row = {"product": c, "seed": seed, "auroc": roc_auc_score(labels, scores), "ours": ours,
               "baseline_single_threshold": base,
               "baseline_random_review_escape": random_abstention(scores, labels, tau95, ours["review_rate"]),
               "policy": pol.to_dict(), "aurc": rc["aurc"],
               "v0_real_only": outcome_stats(scores, labels, cal_real_only.policy.tau_pass, cal_real_only.policy.tau_fail),
               "promised_escape": pol.promised_escape, "synthetic_detect_rate": float(np.mean(syn_sc > pol.tau_pass))}
        rows.append(row)
        print(f"{c:11s} s{seed} AUROC {row['auroc']:.3f} | ours: review {ours['review_rate']:.1%} (@3% prev {ours['review_rate_at_3pct']:.1%}) escape {ours['escape_rate']:.1%} "
              f"FR {ours['false_reject_rate']:.1%} | single-thr: escape {base['escape_rate']:.1%} FR {base['false_reject_rate']:.1%} "
              f"| promised {pol.promised_escape:.1%} | v0 escape {row['v0_real_only']['escape_rate']:.1%}", flush=True)
tag = model.split("/")[-1] + f"_{res}"
(out / f"p1_{tag}.json").write_text(json.dumps(rows, indent=1))
def avg(k1, k2=None):
    return np.mean([r[k1][k2] if k2 else r[k1] for r in rows])
print(f"\nMEAN AUROC {avg('auroc'):.3f} | ours review {avg('ours','review_rate'):.1%} (@3% prevalence {avg('ours','review_rate_at_3pct'):.1%}) escape {avg('ours','escape_rate'):.1%} FR {avg('ours','false_reject_rate'):.1%}"
      f" | single-threshold escape {avg('baseline_single_threshold','escape_rate'):.1%} FR {avg('baseline_single_threshold','false_reject_rate'):.1%}"
      f" | random-review escape {np.mean([r['baseline_random_review_escape'] for r in rows]):.1%}"
      f" | v0(real-only) escape {np.mean([r['v0_real_only']['escape_rate'] for r in rows]):.1%} review@3% {np.mean([r['v0_real_only']['review_rate_at_3pct'] for r in rows]):.1%}"
      f" | AURC {avg('aurc'):.3f}")
