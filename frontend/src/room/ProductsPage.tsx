import React, { useState } from 'react';
import { api, Summary } from '../api';
import { useStore } from '../store';
import { Btn, Panel, decisionColor, pct } from '../ui/bits';
import { Chip, Confirm, PageHead, can, roleName } from './common';

function ProductCard({ s }: { s: Summary }) {
  const { role, refresh, setSessionId, setAct, setError, views } = useStore();
  const thumb = views[s.id]?.photos?.[0];
  const [budget, setBudget] = useState<number>(s.budget ?? 0.1);
  const [fr, setFr] = useState<number>(s.policy?.alpha_fr ?? 0.02);
  const [auto, setAuto] = useState<boolean>(s.autopilot ?? true);
  const [msg, setMsg] = useState<string | null>(null);
  const [check, setCheck] = useState<string | null>(null);
  const qm = can(role, 'QUALITY_MANAGER', 'ADMIN');
  const save = async () => {
    try {
      const r = await api.productSettings(s.id, { budget, falseRejectGuarantee: fr, autopilot: auto });
      setMsg(`Saved. Pass line ${r.policy.tau_pass.toFixed(3)}, fail line ${r.policy.tau_fail.toFixed(3)}.`);
      refresh(s.id);
    } catch (e: any) { setError(e.message); }
  };
  const forget = async () => {
    setCheck('Re-testing the probe set…');
    try {
      const f = await api.forgetting(s.id);
      const b = f.baseline, l = f.latest;
      setCheck(`Good parts passed: ${l.goodsPassed}/${l.goods} now vs ${b.goodsPassed}/${b.goods} at the start. Defects caught: ${l.defectsFlagged}/${l.defects} vs ${b.defectsFlagged}/${b.defects}.`);
    } catch (e: any) { setCheck(null); setError(e.message); }
  };
  const del = async () => {
    try { await api.deleteSession(s.id); window.location.reload(); } catch (e: any) { setError(e.message); }
  };
  const perf = s.performance;
  return (
    <Panel>
      <div className="flex gap-4 flex-wrap">
        {thumb ? <img src={thumb} alt="" className="w-28 h-28 rounded-xl object-cover" /> : <div className="w-28 h-28 rounded-xl bg-raised" />}
        <div className="flex-1 min-w-[220px]">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-xl font-semibold">{(s.displayName ?? s.name).replace(/^\d+/, '')}</h2>
            <Chip>{s.source}</Chip><Chip>{s.plant}</Chip>
            {s.shiftAlarm ? <Chip tone="var(--doubt)">conditions changed</Chip> : <Chip tone="var(--pass)">{s.stage.toLowerCase()}</Chip>}
            {s.hasTwin && !s.relief && <Chip tone="var(--hold)">3D twin</Chip>}{s.relief && <Chip tone="var(--hold)">3D relief</Chip>}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-3 text-sm num">
            <div><div className="text-mist text-xs">Good references</div>{s.refs}</div>
            <div><div className="text-mist text-xs">Parts inspected</div>{s.records}</div>
            <div><div className="text-mist text-xs">Pass / fail line</div>{s.policy ? `${s.policy.tau_pass.toFixed(3)} / ${s.policy.tau_fail.toFixed(3)}` : '—'}</div>
            <div><div className="text-mist text-xs">Escapes (us vs typical)</div>{perf?.ours ? <span><span style={{ color: decisionColor.PASS }}>{perf.ours.escapes}</span> vs {perf.naive?.escapes}</span> : '—'}</div>
          </div>
          <div className="flex gap-2 mt-3 flex-wrap">
            <Btn tone="doubt" onClick={() => { setSessionId(s.id); setAct('line'); }}>Open the line</Btn>
            <Btn tone="ghost" onClick={forget}>Did learning break anything?</Btn>
            <Confirm label="Delete this product line" onYes={del} disabled={!qm} title={qm ? undefined : 'Quality manager or admin only'} />
          </div>
          {check && <p className="text-sm mt-2">{check}</p>}
        </div>
        <div className="w-full lg:w-80 bg-raised rounded-xl p-3 text-sm space-y-3">
          <div className="font-semibold">Guarantees for this product {!qm && <span className="text-mist font-normal text-xs">(read-only for {roleName(role)})</span>}</div>
          <label className="block">Human review budget <span className="num float-right">{pct(budget, 0)}</span>
            <input type="range" min={0.02} max={0.3} step={0.01} value={budget} disabled={!qm} onChange={e => setBudget(+e.target.value)} className="w-full" /></label>
          <label className="block">Good parts wrongly rejected, at most <span className="num float-right">{pct(fr, 1)}</span>
            <input type="range" min={0.005} max={0.1} step={0.005} value={fr} disabled={!qm} onChange={e => setFr(+e.target.value)} className="w-full" /></label>
          <label className="flex items-center gap-2"><input type="checkbox" checked={auto} disabled={!qm} onChange={e => setAuto(e.target.checked)} /> Review-budget autopilot (may raise the pass line, never the fail line)</label>
          <Btn tone="doubt" disabled={!qm} onClick={save}>Recalibrate</Btn>
          {msg && <p className="text-xs text-pass">{msg}</p>}
        </div>
      </div>
    </Panel>
  );
}

export default function ProductsPage() {
  const { views, setAct } = useStore();
  const list = Object.values(views).map(v => v.summary).filter(Boolean) as Summary[];
  return (
    <div className="space-y-5">
      <PageHead title="Products" sub="Every product line on this station: its references, calibrated lines, guarantees and whether learning ever broke what it knew."
        aside={<Btn tone="doubt" onClick={() => setAct('choose')}>Add a product</Btn>} />
      {list.length ? list.map(s => <ProductCard key={s.id} s={s} />) : <Panel><p className="text-mist">No product lines yet.</p></Panel>}
    </div>
  );
}
