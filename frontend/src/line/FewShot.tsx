import React, { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { Btn, Panel, Voice, pct } from '../ui/bits';
import { Kpi, PageHead } from '../room/common';
import { Measured } from './common';

const NAMES: Record<string, string> = { pcb1: 'Ultrasonic sensor (front)', pcb2: 'Ultrasonic sensor (back)', pcb3: 'IR sensor module', pcb4: 'Li-ion charger board' };
type Pt = { n: number; auroc: number; aurocMin: number; aurocMax: number; caught: number; falseAlarms: number; patches: number };

function Curve({ pts, i, onPick }: { pts: Pt[]; i: number; onPick: (i: number) => void }) {
  const W = 520, H = 250, L = 44, R = 16, T = 14, B = 34;
  const lo = Math.floor(Math.min(...pts.map(p => p.aurocMin)) * 10) / 10;
  const x = (n: number) => L + ((n - 1) / 29) * (W - L - R);
  const y = (v: number) => T + (1 - (v - lo) / (1 - lo)) * (H - T - B);
  const path = (k: 'auroc') => pts.map((p, j) => `${j ? 'L' : 'M'}${x(p.n).toFixed(1)},${y(p[k]).toFixed(1)}`).join(' ');
  const band = pts.map((p, j) => `${j ? 'L' : 'M'}${x(p.n)},${y(p.aurocMax)}`).join(' ') + ' ' + [...pts].reverse().map(p => `L${x(p.n)},${y(p.aurocMin)}`).join(' ') + ' Z';
  const ticks = [lo, (lo + 1) / 2, 1];
  const cur = pts[i];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Accuracy against number of good photos">
      {ticks.map(t => (
        <g key={t}>
          <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke="var(--line)" strokeOpacity={0.18} />
          <text x={L - 6} y={y(t) + 4} textAnchor="end" fontSize="10" fill="var(--mist)" className="mono">{t.toFixed(2)}</text>
        </g>
      ))}
      <line x1={x(cur.n)} x2={x(cur.n)} y1={T} y2={H - B} stroke="var(--bone)" strokeDasharray="3 4" strokeOpacity={0.5} style={{ transition: 'all .35s' }} />
      <path d={band} fill="var(--bone)" fillOpacity={0.09} />
      <path d={path('auroc')} fill="none" stroke="var(--bone)" strokeWidth={2.5} />
      {pts.map((p, j) => (
        <g key={p.n} onClick={() => onPick(j)} style={{ cursor: 'pointer' }}>
          <rect x={x(p.n) - 12} y={T} width={24} height={H - T} fill="transparent" />
          <circle cx={x(p.n)} cy={y(p.auroc)} r={j === i ? 7 : 3.5} fill={j === i ? 'var(--accent)' : 'var(--bone)'} stroke="var(--bone)" strokeWidth={j === i ? 2 : 0} />
          <text x={x(p.n)} y={H - 14} textAnchor="middle" fontSize="11" fill={j === i ? 'var(--bone)' : 'var(--mist)'} fontWeight={j === i ? 700 : 400} className="mono">{p.n}</text>
        </g>
      ))}
      <text x={(L + W - R) / 2} y={H - 1} textAnchor="middle" fontSize="10" fill="var(--mist)">good photos learned from</text>
    </svg>
  );
}

/** Thirty is enough: measured accuracy against the number of good photos, with the picture behind each point. */
export default function FewShot() {
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [prod, setProd] = useState('pcb4');
  const [i, setI] = useState(0);
  const [ex, setEx] = useState(0);
  const [truth, setTruth] = useState(false);
  const [playing, setPlaying] = useState(true);
  useEffect(() => { api.fewshot().then(r => { setD(r); if (!r.products[prod]) setProd(Object.keys(r.products)[0]); }).catch(e => setErr(e.message)); /* eslint-disable-next-line */ }, []);
  const p = d?.products?.[prod];
  const pts: Pt[] = p?.curve ?? [];
  useEffect(() => { setI(0); setEx(0); setPlaying(true); }, [prod]);
  useEffect(() => {
    if (!playing || !pts.length) return;
    if (i >= pts.length - 1) { setPlaying(false); return; }
    const t = setTimeout(() => setI(k => k + 1), 1100);
    return () => clearTimeout(t);
  }, [playing, i, pts.length]);
  // preload every frame so the scrub is instant
  useEffect(() => { if (p) pts.forEach(q => p.examples.forEach((e: any) => { const im = new Image(); im.src = `/api/fewshot/img/${prod}_${e.k}_n${q.n}.jpg`; })); /* eslint-disable-next-line */ }, [prod, !!p]);
  const all = useMemo(() => (d ? Object.entries(d.products) as [string, any][] : []), [d]);

  if (err) return <PageHead title="Thirty is enough" sub={err} />;
  if (!p) return <PageHead title="Thirty is enough" sub="Loading…" />;
  const cur = pts[i], last = pts[pts.length - 1], e = p.examples[ex];
  return (
    <div className="space-y-4">
      <PageHead title="Thirty good photos. No training."
        sub="A conventional inspection model needs thousands of labelled images and hours of training per product. This station only remembers what good looks like. Drag the number of photos and watch what it can see. Every point below is measured on boards it never saw."
        aside={<Measured />} />
      <div className="flex flex-wrap gap-2">
        {all.map(([k]) => (
          <button key={k} onClick={() => setProd(k)} className={`btn px-4 h-9 text-sm border border-line ${k === prod ? 'font-semibold' : 'bg-surface'}`} style={k === prod ? { background: 'var(--bone)', color: 'var(--ink)' } : undefined}>
            <span className="mono text-[11px] opacity-70 mr-2">{k.toUpperCase()}</span>{NAMES[k] ?? k}
          </button>
        ))}
      </div>

      <div className="panel p-5">
        <div className="flex flex-wrap items-end gap-x-8 gap-y-3">
          <div>
            <div className="label">Good photos learned from</div>
            <div className="display num leading-none" style={{ fontSize: 96, fontFamily: 'var(--font-display)' }}>{cur.n}</div>
          </div>
          <div className="flex-1 min-w-[260px] pb-3">
            <div className="flex gap-2">
              {pts.map((q, j) => (
                <button key={q.n} onClick={() => { setPlaying(false); setI(j); }} className="flex-1 h-12 border border-line num text-lg font-semibold transition"
                  style={{ borderRadius: 14, background: j === i ? 'var(--bone)' : j < i ? 'var(--raised)' : 'var(--surface)', color: j === i ? 'var(--surface)' : 'var(--bone)' }}>{q.n}</button>
              ))}
            </div>
            <div className="flex items-center gap-3 mt-3">
              <Btn tone="accent" onClick={() => { if (i >= pts.length - 1) setI(0); setPlaying(v => !v); }}>{playing ? 'Pause' : i >= pts.length - 1 ? 'Replay from 1 photo' : 'Play'}</Btn>
              <span className="text-sm text-mist">Training steps: <b className="text-bone num">0</b> · Defect photos used: <b className="text-bone num">0</b> · Labels: <b className="text-bone num">0</b></span>
            </div>
          </div>
        </div>
      </div>

      <div className="grid xl:grid-cols-[1fr_1fr_1.15fr] gap-4">
        <Panel title={`What it has seen: ${cur.n} of 30`}>
          <div className="relative overflow-hidden" style={{ borderRadius: 12 }}>
            <img src={`/api/fewshot/img/${prod}_refs.jpg`} alt="The reference photos" className="w-full block" />
            <div className="absolute inset-0 grid grid-cols-6 grid-rows-5">
              {Array.from({ length: 30 }, (_, k) => (
                <div key={k} style={{ background: k < cur.n ? 'transparent' : 'rgb(var(--ink-rgb) / 0.9)', outline: k < cur.n ? '1px solid rgb(var(--accent-rgb) / 0.9)' : '1px solid rgb(var(--line-rgb) / 0.12)', outlineOffset: -1, transition: 'background .4s' }} />
              ))}
            </div>
          </div>
          <p className="text-xs text-mist mt-2">Good boards only. {cur.patches.toLocaleString('en-IN')} small patches of "normal" in memory. Nothing is trained; adding a photo takes a fraction of a second.</p>
        </Panel>

        <Panel title="What it sees on a defective board" aside={
          <div className="flex gap-1 text-[12px]">
            {p.examples.map((x: any, k: number) => <button key={k} onClick={() => { setEx(k); setTruth(false); }} className="btn px-2.5 h-7 border border-line" style={k === ex && !truth ? { background: 'var(--bone)', color: 'var(--ink)' } : undefined}>{x.defect.split(',')[0]}</button>)}
            <button onClick={() => setTruth(v => !v)} className="btn px-2.5 h-7 border border-line" style={truth ? { background: 'var(--fail)', color: '#ffffff' } : undefined}>truth</button>
          </div>}>
          <div className="relative overflow-hidden bg-raised aspect-square" style={{ borderRadius: 12 }}>
            {pts.map((q, j) => (
              <img key={q.n} src={`/api/fewshot/img/${prod}_${e.k}_n${q.n}.jpg`} alt="" className="absolute inset-0 w-full h-full object-cover" style={{ opacity: j === i && !truth ? 1 : 0, transition: 'opacity .45s', filter: 'brightness(1.5) contrast(1.05)' }} />
            ))}
            <img src={`/api/fewshot/img/${prod}_${e.k}_truth.jpg`} alt="Where the defect really is" className="absolute inset-0 w-full h-full object-cover" style={{ opacity: truth ? 1 : 0, transition: 'opacity .3s' }} />
            <span className="absolute left-2 top-2 px-2 py-0.5 text-[11px] mono" style={{ background: '#121212', color: '#fff', borderRadius: 999 }}>{truth ? 'ground truth outline' : `after ${cur.n} photo${cur.n > 1 ? 's' : ''}`}</span>
          </div>
          <p className="text-xs text-mist mt-2">Same board, same colour scale at every step. With few photos, normal variation glows too. As photos are added the noise dies away and the real defect ({e.defect}) is what remains.</p>
        </Panel>

        <Panel title="Measured on held-out boards">
          <Curve pts={pts} i={i} onPick={j => { setPlaying(false); setI(j); }} />
          <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-mist mt-1">
            <span><i className="inline-block w-4 h-[3px] align-middle mr-1.5" style={{ background: 'var(--bone)' }} />AUROC: how often a defective board scores above a good one (0.5 = coin toss, 1 = always)</span>
            <span>band = 3 random draws of the photos</span>
          </div>
          <div className="grid grid-cols-3 gap-2 mt-3">
            <Kpi label={`AUROC, ${cur.n} photo${cur.n > 1 ? 's' : ''}`} value={cur.auroc.toFixed(3)} sub={`worst draw ${cur.aurocMin.toFixed(3)}`} />
            <Kpi label="AUROC, 30 photos" value={last.auroc.toFixed(3)} sub={`worst draw ${last.aurocMin.toFixed(3)}`} />
            <Kpi label="Of the 30-photo skill" value={pct((cur.auroc - 0.5) / (last.auroc - 0.5), 0)} sub="already there" tone="var(--pass)" />
          </div>
        </Panel>
      </div>

      <div className="grid xl:grid-cols-[1.3fr_1fr] gap-4">
        <Panel title="All four boards, one method">
          <table className="w-full text-sm num">
            <thead className="text-mist text-xs text-left"><tr><th className="py-1">Board</th>{pts.map(q => <th key={q.n} className="text-right">{q.n} photo{q.n > 1 ? 's' : ''}</th>)}<th className="text-right">Test boards</th></tr></thead>
            <tbody>
              {all.map(([k, v]) => (
                <tr key={k} className={`border-t border-line cursor-pointer ${k === prod ? 'bg-raised' : ''}`} onClick={() => setProd(k)}>
                  <td className="py-1.5"><span className="mono text-[11px] text-mist mr-2">{k}</span>{NAMES[k] ?? k}</td>
                  {v.curve.map((q: Pt, j: number) => <td key={q.n} className="text-right" style={{ fontWeight: k === prod && j === i ? 700 : 400 }}>{q.auroc.toFixed(3)}</td>)}
                  <td className="text-right text-mist">{v.testBoards}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-xs text-mist mt-2">AUROC of the patch-memory detector alone, before the golden-board and component checks are added. Nothing was tuned per board: the same code learned all four.</p>
        </Panel>
        <Panel title="Why this is the point">
          <Voice>A new product on Monday should not need a data team until March.</Voice>
          <ul className="text-sm list-disc pl-5 mt-3 space-y-1.5">
            <li>The backbone is frozen. Learning a board means storing patches of good boards, so there is no training run, no GPU hours and nothing to overfit.</li>
            <li>No defect photo is needed to start. Defects are rare and never look the same twice; good boards are what a factory has on day one.</li>
            <li>Most of the skill arrives in the first handful of photos and each extra photo adds less. Past thirty the station keeps learning from boards a person approves, while the line runs.</li>
          </ul>
        </Panel>
      </div>
      <p className="text-xs text-mist">{d.note}</p>
    </div>
  );
}
