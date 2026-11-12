"""Risk-coverage report (a PS-12 deliverable): one self-contained HTML page plus a decisions CSV."""
from __future__ import annotations

import csv
import html
import io
import json
import time

import numpy as np

from .data import DATA_ROOT

E = html.escape


def _svg_curve(rc: dict | None, naive_escape: float | None, w: int = 560, h: int = 260) -> str:
    if not rc:
        return "<p class='mut'>Run parts with known truth to draw the measured curve.</p>"
    xs, ys = np.array(rc["review"]), np.array(rc["escape"])
    pad = 40
    X = lambda v: pad + (w - pad - 10) * v / max(xs.max(), 1e-9)  # noqa: E731
    Y = lambda v: h - pad - (h - pad - 10) * v / max(ys.max(), naive_escape or 0, 1e-9)  # noqa: E731
    pts = " ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in zip(xs, ys))
    grid = "".join(f"<line x1='{pad}' x2='{w - 10}' y1='{Y(t):.1f}' y2='{Y(t):.1f}' class='g'/>"
                   f"<text x='{pad - 6}' y='{Y(t) + 4:.1f}' text-anchor='end'>{t:.0%}</text>"
                   for t in np.linspace(0, max(ys.max(), naive_escape or 0), 5))
    xt = "".join(f"<text x='{X(t):.1f}' y='{h - pad + 18}' text-anchor='middle'>{t:.0%}</text>" for t in np.linspace(0, xs.max(), 6))
    naive = (f"<circle cx='{X(0):.1f}' cy='{Y(naive_escape):.1f}' r='6' class='nv'/>"
             f"<text x='{X(0) + 12:.1f}' y='{Y(naive_escape) + 18:.1f}' class='nvt'>typical single-threshold AI</text>"
             if naive_escape is not None else "")
    return (f"<svg viewBox='0 0 {w} {h}' role='img' aria-label='Defect escapes versus share of parts sent to a person'>"
            f"{grid}{xt}<polyline points='{pts}' class='c'/>{naive}"
            f"<text x='{(w + pad) / 2:.0f}' y='{h - 4}' text-anchor='middle'>parts sent to a person</text></svg>")


def build_html(session) -> str:
    perf = session.performance()
    pol = session.cal.policy
    rc = perf.get("riskCoverage") if perf.get("n") else None
    naive_esc = perf.get("naiveEscapeRate") if perf.get("n") else None
    events = [e for e in session.timeline if e["kind"] in ("shift.alarm", "shift.adapted", "chaos.conditions", "hive.received")]
    bench = ""
    f = DATA_ROOT / "results" / "p1_dinov2-small_672.json"
    if f.exists():
        rows = json.loads(f.read_text())
        mean = lambda k1, k2=None: float(np.mean([r[k1][k2] if k2 else r[k1] for r in rows]))  # noqa: E731
        bench = (f"<h2>Benchmark on public data</h2><p>VisA, 12 products × 3 seeds, 30 good + 5 defect photos each "
                 f"({len(rows)} runs). Same false-reject rate for both systems.</p><table>"
                 f"<tr><th></th><th>Defects escaped</th><th>Good wrongly rejected</th><th>Sent to a person (3% defect line)</th></tr>"
                 f"<tr><td>Typical single-threshold AI</td><td>{mean('baseline_single_threshold', 'escape_rate'):.1%}</td>"
                 f"<td>{mean('baseline_single_threshold', 'false_reject_rate'):.1%}</td><td>0%</td></tr>"
                 f"<tr><td>Sandeha</td><td><b>{mean('ours', 'escape_rate'):.1%}</b></td><td>{mean('ours', 'false_reject_rate'):.1%}</td>"
                 f"<td>{mean('ours', 'review_rate_at_3pct'):.1%}</td></tr></table>"
                 f"<p class='mut'>Mean AUROC {mean('auroc'):.3f}.</p>")
    o, nv = perf.get("ours") or {}, perf.get("naive") or {}
    live = (f"<table><tr><th></th><th>Typical AI</th><th>Sandeha</th></tr>"
            f"<tr><td>Defects shipped</td><td>{nv.get('escapes', '–')}</td><td><b>{o.get('escapes', '–')}</b></td></tr>"
            f"<tr><td>Good parts scrapped</td><td>{nv.get('falseRejects', '–')}</td><td>{o.get('falseRejects', '–')}</td></tr>"
            f"<tr><td>Sent to a person</td><td>0</td><td>{o.get('reviewed', '–')}</td></tr></table>"
            f"<p class='mut'>{perf.get('n', 0)} parts with known truth ({perf.get('defects', 0)} defective).</p>"
            if perf.get("n") else "<p class='mut'>No parts with known truth yet.</p>")
    ev = "".join(f"<li>{E(time.strftime('%H:%M:%S', time.localtime(e['t'])))} — {E(e['text'])}</li>" for e in events) or "<li>No shifts or adaptations.</li>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sandeha risk-coverage report</title><style>
:root{{--bg:#fff;--fg:#151a33;--mut:#5b6478;--acc:#c97a10;--line:#e3e6ef}}
@media (prefers-color-scheme:dark){{:root{{--bg:#10142e;--fg:#ece7da;--mut:#8f97c2;--acc:#f2a93b;--line:#2f3769}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,sans-serif;max-width:820px;margin:auto;padding:24px 16px}}
h1{{font-size:28px;margin:0 0 4px}}h2{{font-size:18px;margin-top:32px}}.mut{{color:var(--mut)}}
table{{border-collapse:collapse;width:100%;margin:8px 0}}td,th{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left}}
svg{{width:100%;height:auto;margin-top:8px}}svg text{{fill:var(--mut);font-size:11px}}.g{{stroke:var(--line)}}
.c{{fill:none;stroke:var(--acc);stroke-width:2.5}}.nv{{fill:#f0655a}}.nvt{{fill:#f0655a!important}}
</style></head><body>
<h1>Risk–coverage report</h1>
<p class="mut">{E(session.source)} / {E(session.product.name)} · {E(session.plant)} · generated {time.strftime('%Y-%m-%d %H:%M')}</p>
<h2>How decisions are made</h2>
<table><tr><td>Pass line (approve on my own at or below)</td><td>{pol.tau_pass:.4f}</td></tr>
<tr><td>Fail line (reject on my own above)</td><td>{pol.tau_fail:.4f}</td></tr>
<tr><td>Guarantee: good parts wrongly rejected</td><td>at most {pol.alpha_fr:.0%} (split-conformal, {pol.n_good_calib} leave-one-out references)</td></tr>
<tr><td>Estimated defect escape rate</td><td>{pol.promised_escape:.1%} (90% upper bound {pol.escape_upper_90:.1%}); an estimate from {pol.n_defect_calib} real + imagined defects</td></tr>
<tr><td>Human review budget</td><td>{pol.budget:.0%}, enforced live by the review-budget autopilot</td></tr></table>
<h2>Defects that escape vs. parts sent to a person (measured on this line)</h2>
{_svg_curve(rc, naive_esc)}
<h2>Same parts, two inspectors</h2>{live}
<h2>Changes on the line</h2><ul>{ev}</ul>
{bench}
<h2>Limits of this report</h2><ul>
<li>Ground truth comes from the public datasets the parts were drawn from; uploaded test photos without labels are not counted.</li>
<li>The escape estimate before deployment relies on imagined defects and can be off in either direction; the measured curve above is the reference.</li>
<li>The shift alarm's false-alarm rate is measured empirically, not a proven bound.</li></ul>
</body></html>"""


def decisions_csv(session) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "time", "decision", "doubt_reason", "score", "pass_line", "uncertainty", "typical_ai_decision",
                "truth", "defect_type", "reviewed_as", "reviewers", "hotspot_x", "hotspot_y"])
    for r in session.records:
        if r.ghost:
            continue
        w.writerow([r.id, r.created, r.decision, r.doubt_reason or "", r.score, r.pass_line, r.uncertainty,
                    r.naive_decision, "" if r.truth is None else r.truth, r.defect_type or "",
                    r.review.get("final", ""), r.review.get("by", ""), r.hotspot["x"], r.hotspot["y"]])
    return buf.getvalue()
