import React, { useEffect, useMemo, useState } from 'react';
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api, BlindSpots, Certificate, Edge, Performance, TrustCurve } from '../api';
import { useStore, useInterval } from '../store';
import { Btn, Panel, pct, rupees, Stat, Voice } from '../ui/bits';

function Benchmark() {
  const [rows, setRows] = useState<any[] | null>(null);
  useEffect(() => {
    api.results().then(r => {
      const key = Object.keys(r).find(k => k.includes('672')) ?? Object.keys(r)[0];
      setRows(key ? r[key] : []);
    }).catch(() => setRows([]));
  }, []);
  const byProduct = useMemo(() => {
    if (!rows) return [];
    const m: Record<string, any[]> = {};
    rows.forEach(x => (m[x.product] ??= []).push(x));
    const avg = (xs: any[], f: (x: any) => number) => xs.reduce((a, x) => a + f(x), 0) / xs.length;
    return Object.entries(m).map(([p, xs]) => ({
      product: p, n: xs.length, auroc: avg(xs, x => x.auroc),
      ours: avg(xs, x => x.ours.escape_rate), naive: avg(xs, x => x.baseline_single_threshold.escape_rate),
      review: avg(xs, x => x.ours.review_rate_at_3pct ?? x.ours.review_rate), fr: avg(xs, x => x.ours.false_reject_rate)
    }));
  }, [rows]);
  if (!rows) return null;
  if (!rows.length) return <Panel title="Measured on public data"><p className="text-mist">Run the benchmark script to fill this table.</p></Panel>;
  const mean = (f: (x: any) => number) => byProduct.reduce((a, x) => a + f(x), 0) / byProduct.length;
  return (
    <Panel title="Measured on 12 VisA products, 30 good + 5 defect photos each" aside={<span className="text-mist text-sm">{rows.length} runs</span>}>
      <div className="flex gap-10 mb-4">
        <Stat value={pct(mean(x => x.naive))} label="defects escape a typical AI" tone="FAIL" />
        <Stat value={pct(mean(x => x.ours))} label="escape Sandeha" tone="PASS" />
        <Stat value={pct(mean(x => x.review))} label="parts sent to a person (3% defect line)" tone="DOUBT" />
      </div>
      <div className="max-h-64 overflow-auto">
        <table className="w-full text-sm num">
          <thead className="text-mist sticky top-0 bg-surface"><tr><th className="text-left font-normal">Product</th><th className="text-right font-normal">AUROC</th><th className="text-right font-normal">Typical AI escapes</th><th className="text-right font-normal">Sandeha escapes</th><th className="text-right font-normal">To a person</th><th className="text-right font-normal">Good scrapped</th></tr></thead>
          <tbody>
            {byProduct.map(r => (
              <tr key={r.product} className="border-t border-line">
                <td className="py-1.5">{r.product}</td><td className="text-right">{r.auroc.toFixed(3)}</td>
                <td className="text-right">{pct(r.naive)}</td><td className="text-right text-pass">{pct(r.ours)}</td>
                <td className="text-right">{pct(r.review)}</td><td className="text-right">{pct(r.fr)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function blindStory(r: BlindSpots) {
  const weak = r.cells.filter(c => c.state === 'blind' || c.state === 'large').length;
  return `I planted ${r.tested} ${r.kind}es across ${r.regions} regions of the part. Typically I catch one ${r.medianMinSizePct ?? '—'}% of the photo wide; `
    + (weak ? `${weak} region(s) need a large one${r.blindCells ? `, ${r.blindCells} I missed entirely` : ''} — look harder there.` : 'no region needs more than a medium one.')
    + (r.untestableCells ? ` In ${r.untestableCells} region(s) the planted ${r.kind} blended into the surface, so those are untested, not blind.` : '');
}

function BlindSpotAtlas({ sessionId }: { sessionId: string }) {
  const { setError } = useStore();
  const [res, setRes] = useState<BlindSpots | null>(null);
  const [kind, setKind] = useState('scratch');
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try { setRes(await api.blindSpots(sessionId, kind)); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  return (
    <Panel title="Where I'm half-blind" aside={
      <div className="flex gap-2 items-center">
        <select value={kind} onChange={e => setKind(e.target.value)} className="bg-raised rounded-lg px-2 py-1 text-sm" aria-label="Defect kind">
          {['scratch', 'stain', 'crack', 'burr', 'fiber'].map(k => <option key={k}>{k}</option>)}
        </select>
        <Btn tone="ghost" onClick={run} disabled={busy}>{busy ? 'Testing myself…' : 'Map my blind spots'}</Btn>
      </div>}>
      <div className="grid md:grid-cols-[300px_1fr] gap-5 items-start">
        {res ? <img src={res.image} alt="Blind-spot atlas" className="rounded-xl w-full" /> : <div className="aspect-square rounded-xl bg-raised grid place-items-center text-mist text-sm p-6 text-center">I'll plant {kind}es of growing size in every region and record the smallest one I catch.</div>}
        <div>
          <Voice>{res ? blindStory(res) : 'Every inspection system has weak spots. Mine are measured and shown, so you know where a person should look harder.'}</Voice>
          {res && <div className="grid grid-cols-5 gap-2 mt-4">
            {([['sharp', 'bg-pass', `catches ≤${res.sizesPct[1]}%`], ['medium', 'bg-doubt', `needs ${res.sizesPct[2]}–${res.sizesPct[3]}%`],
              ['large', 'bg-fail/70', `only ${res.sizesPct[4]}%`], ['blind', 'bg-fail', 'missed all'], ['untestable', 'bg-mist', 'defect not visible']] as const).map(([st, c, t]) =>
              <div key={st} className="bg-raised rounded-lg p-2">
                <div className="flex items-center gap-2 text-xs text-mist"><span className={`w-2.5 h-2.5 rounded-sm ${c}`} />{st}</div>
                <div className="text-xl tabular-nums">{res.cells.filter(x => x.state === st).length}</div>
                <div className="text-[11px] text-mist">{t}</div>
              </div>)}
          </div>}
          {res && <p className="text-xs text-mist mt-3">Sizes are % of the photo width. {res.tested} planted defects, each scored like a live part (the photo it sits on is left out of memory) and counted only if my heatmap points at it. {res.vlmChecked ? `${res.vlmChecked} misses were double-checked by the local vision-language model.` : ''}</p>}
        </div>
      </div>
    </Panel>
  );
}

function EdgeProof() {
  const [e, setE] = useState<Edge | null>(null);
  useEffect(() => { api.edge().then(setE).catch(() => {}); }, []);
  if (!e?.measured || !e.rows) return null;
  const best = e.rows.filter(r => r.fps >= 5).sort((a, b) => b.resolution - a.resolution)[0];
  return (
    <Panel title="Runs without a GPU" aside={<span className="text-mist text-sm">{e.device}</span>}>
      <div className="flex gap-10 mb-4">
        {best && <Stat value={`${best.fps} fps`} label={`${best.precision}, ${best.resolution}px input`} tone="PASS" />}
        <Stat value={`${e.sizeMBint8} MB`} label="model size after INT8" />
      </div>
      <table className="w-full text-sm num">
        <thead className="text-mist"><tr><th className="text-left font-normal">Precision</th><th className="text-right font-normal">Input</th><th className="text-right font-normal">Parts / second</th><th className="text-right font-normal">ms per part</th></tr></thead>
        <tbody>{e.rows.map((r, i) => (
          <tr key={i} className="border-t border-line"><td className="py-1.5">{r.precision}</td><td className="text-right">{r.resolution}px</td><td className={`text-right ${r.fps >= 5 ? 'text-pass' : ''}`}>{r.fps}</td><td className="text-right">{r.msPerPart}</td></tr>
        ))}</tbody>
      </table>
      <p className="text-mist text-xs mt-2">{e.note}</p>
    </Panel>
  );
}

export default function Trust() {
  const { sessionId, setError, view } = useStore();
  const [curve, setCurve] = useState<TrustCurve | null>(null);
  const [idx, setIdx] = useState(4);
  const [perf, setPerf] = useState<Performance | null>(null);
  const [cert, setCert] = useState<Certificate | null>(null);
  const [applied, setApplied] = useState('');

  useEffect(() => {
    if (!sessionId) return;
    api.trust(sessionId).then(c => {
      setCurve(c);
      // open on the strictest promise that still fits the human budget
      const k = c.rows.findIndex(r => r.reviewRate <= 0.12);
      setIdx(k === -1 ? c.rows.length - 1 : k);
    }).catch(e => setError(e.message));
  }, [sessionId, setError]);
  useInterval(() => { if (sessionId) api.performance(sessionId).then(setPerf).catch(() => {}); }, 2500, [sessionId]);
  if (!sessionId) return null;
  const row = curve?.rows[Math.min(idx, (curve?.rows.length ?? 1) - 1)];

  const rc = perf?.riskCoverage;
  const rcData = rc ? rc.review.map((r, i) => ({ review: Math.round(r * 100), sandeha: +(rc.escape[i] * 100).toFixed(1) })) : [];

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        <Panel title="The trust contract">
          {curve && row ? (
            <>
              <Voice>Tell me how many bad parts per million you can accept. I'll tell you what it costs in human checks.</Voice>
              <input className="w-full mt-5" type="range" min={0} max={curve.rows.length - 1} value={idx} onChange={e => setIdx(+e.target.value)} aria-label="Escape target" />
              <div className="grid grid-cols-2 md:grid-cols-4 gap-5 mt-4">
                <Stat value={Math.round(row.ppm).toLocaleString()} label="bad parts per million shipped" />
                <Stat value={pct(row.reviewRate)} label="parts a person checks" tone="DOUBT" />
                <Stat value={row.inspectorHours.toFixed(1)} label="inspector hours per shift" />
                <Stat value={rupees(row.rupeesPerShift)} label="cost of mistakes per shift" />
              </div>
              <p className="text-mist text-sm mt-4">
                A typical single-threshold AI ships {Math.round(curve.naive.ppm).toLocaleString()} bad parts per million and costs {rupees(curve.naive.rupeesPerShift)} per shift on the same assumptions
                ({curve.assumptions.partsPerShift.toLocaleString()} parts, {Math.round(curve.assumptions.prevalence * 100)}% defective, ₹{curve.assumptions.costPerEscape} per escape).
                Upper bound on escapes at 90% confidence: {pct(row.escapeUpper90)}. Calibrated on {curve.calibration.good} good, {curve.calibration.realDefects} real and {curve.calibration.imaginedDefects} imagined defects.
              </p>
              <p className="text-doubt text-sm mt-2">This promise is an estimate made before seeing many real defects, from imagined ones. The curve on the right is what actually happened on this line, and it is what the certificate records.</p>
              <div className="flex gap-2 mt-4 items-center">
                <Btn tone="doubt" onClick={async () => {
                  try { const p = await api.setTarget(sessionId, row.targetEscape, Math.max(0.02, Math.min(0.3, row.reviewRate + 0.02))); setApplied(`Applied: pass line ${p.tau_pass.toFixed(3)}, fail line ${p.tau_fail.toFixed(3)}`); }
                  catch (e: any) { setError(e.message); }
                }}>Apply this contract to the line</Btn>
                {applied && <span className="text-pass text-sm">{applied}</span>}
              </div>
            </>
          ) : <p className="text-mist">Calibrating…</p>}
        </Panel>

        <Panel title="Risk vs. human review, measured live" aside={<span className="text-mist text-sm">{perf?.n ?? 0} parts with known truth</span>}>
          {rcData.length ? (
            <div className="h-72">
              <ResponsiveContainer>
                <LineChart data={rcData} margin={{ top: 8, right: 16, bottom: 18, left: 0 }}>
                  <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" />
                  <XAxis dataKey="review" unit="%" tick={{ fill: 'var(--mist)', fontSize: 12 }} label={{ value: 'parts sent to a person', fill: 'var(--mist)', fontSize: 12, position: 'insideBottom', offset: -10 }} />
                  <YAxis unit="%" tick={{ fill: 'var(--mist)', fontSize: 12 }} />
                  <Tooltip contentStyle={{ background: 'var(--surface)', border: 'none', borderRadius: 12 }} />
                  <Legend />
                  <Line name="defects that escape" dataKey="sandeha" stroke="var(--doubt)" strokeWidth={2.5} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : <p className="text-mist">Run parts on the line to draw the curve the judges score.</p>}
          {perf?.ours && (
            <p className="text-sm mt-2 num">So far: Sandeha let {perf.ours.escapes} defects through and asked about {perf.ours.reviewed} parts; the typical AI let {perf.naive?.escapes} through.</p>
          )}
        </Panel>
      </div>

      <BlindSpotAtlas sessionId={sessionId} />

      <Benchmark />

      <EdgeProof />

      <Panel title="Risk–coverage report">
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-sm text-mist flex-1 min-w-[260px]">One page for the judges and for your customer: how I decide, the measured escapes against human review, the comparison with a typical AI, every change on the line, and the limits of the numbers.</p>
          <a href={api.reportUrl(sessionId)} target="_blank" rel="noreferrer" className="px-4 py-2 rounded-xl text-sm font-semibold bg-doubt text-ink">Open the report</a>
          <a href={api.reportUrl(sessionId, true)} className="px-4 py-2 rounded-xl text-sm font-semibold bg-raised text-bone">Download it</a>
          <a href={api.csvUrl(sessionId)} className="px-4 py-2 rounded-xl text-sm font-semibold bg-raised text-bone">Every decision (CSV)</a>
        </div>
      </Panel>

      <Panel title="Ship the batch with proof">
        <div className="grid md:grid-cols-[1fr_240px] gap-6 items-start">
          <div>
            <Voice>Every decision in this batch is chained and signed. Your customer scans the code and checks it: nobody, including us, can quietly edit a result.</Voice>
            <div className="mt-4"><Btn tone="doubt" onClick={async () => { try { setCert(await api.certificate(sessionId)); } catch (e: any) { setError(e.message); } }}>Sign the batch certificate</Btn></div>
            {cert && (
              <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm mt-4 num">
                <dt className="text-mist">Certificate</dt><dd>{cert.claim.certificate}</dd>
                <dt className="text-mist">Parts</dt><dd>{cert.claim.parts}</dd>
                <dt className="text-mist">Approved automatically</dt><dd>{cert.claim.autoPassed}</dd>
                <dt className="text-mist">Rejected</dt><dd>{cert.claim.rejected}</dd>
                <dt className="text-mist">Checked by a person</dt><dd>{cert.claim.sentToHuman}</dd>
                <dt className="text-mist">Estimated escape rate</dt><dd>{pct(cert.claim.guarantee.estimatedEscapeRate)} (≤ {pct(cert.claim.guarantee.escapeUpper90)} at 90%)</dd>
                <dt className="text-mist">Verify</dt><dd><a className="text-doubt underline" href={new URL(cert.verifyUrl).pathname} target="_blank" rel="noreferrer">open verification page</a></dd>
              </dl>
            )}
          </div>
          {cert && <img src={cert.qr} alt="Certificate QR code" className="rounded-xl bg-white p-2 w-56" />}
        </div>
      </Panel>
    </div>
  );
}
