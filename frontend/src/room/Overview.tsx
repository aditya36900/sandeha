import React, { useState } from 'react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../api';
import { useStore } from '../store';
import { Btn, Panel, decisionColor, pct, rupees } from '../ui/bits';
import { Chip, DecisionPill, Kpi, PageHead, PassportModal, usePoll } from './common';

export default function Overview() {
  const { setSessionId, setAct } = useStore();
  const [o] = usePoll(api.overview, 5000);
  const [pass, setPass] = useState<string | null>(null);
  if (!o) return <PageHead title="Control room" sub="Loading the station…" />;
  const t = o.totals, m = o.measured;
  const saved = m.costTypicalAI - m.cost;
  return (
    <div className="space-y-5">
      <PageHead title="Control room" sub={`${o.station.name} · every product line on this station, live. Numbers count real inspections only; dataset truth is used where it exists.`} />
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3">
        <Kpi label="Parts inspected" value={t.parts.toLocaleString()} />
        <Kpi label="Passed alone" value={t.pass} tone={decisionColor.PASS} />
        <Kpi label="Rejected" value={t.fail} tone={decisionColor.FAIL} />
        <Kpi label="Asked a person" value={t.doubt} tone={decisionColor.DOUBT} sub={`${pct(t.reviewRate)} review rate (target ≤ 10%)`} />
        <Kpi label="Held on belt" value={t.hold} tone={decisionColor.HOLD} sub={`${pct(t.holdRate)} of parts`} />
        <Kpi label="Latency p50" value={o.latencyMsP50 ? `${Math.round(o.latencyMsP50)} ms` : '—'} sub={o.latencyMsP50 ? `${(1000 / o.latencyMsP50).toFixed(1)} parts/s` : undefined} />
        <Kpi label="Escapes" value={`${m.escapes} vs ${m.escapesTypicalAI}`} sub={`of ${m.defectsSeen} known defects (us vs typical AI)`} tone={m.escapes <= m.escapesTypicalAI ? 'var(--pass)' : 'var(--fail)'} />
        <Kpi label="Cost of mistakes" value={rupees(m.cost)} sub={saved > 0 ? `${rupees(saved)} less than a typical AI` : `typical AI: ${rupees(m.costTypicalAI)}`} />
      </div>

      <div className="grid xl:grid-cols-[minmax(0,1fr)_400px] gap-5">
        <Panel title="Decisions per minute, last 30 minutes" aside={o.trend.every(x => !x.PASS && !x.FAIL && !x.DOUBT && !x.HOLD)
          ? <span className="text-xs text-mist">quiet: no parts in the last 30 minutes</span> : undefined}>
          <div className="h-56">
            <ResponsiveContainer>
              <BarChart data={o.trend} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
                <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" vertical={false} />
                <XAxis dataKey="minute" tick={{ fill: 'var(--mist)', fontSize: 11 }} tickFormatter={v => (v === 0 ? 'now' : `${v}m`)} interval={4} />
                <YAxis allowDecimals={false} tick={{ fill: 'var(--mist)', fontSize: 11 }} />
                <Tooltip contentStyle={{ background: 'var(--surface)', border: 'none', borderRadius: 12 }} cursor={{ fill: 'var(--raised)' }} />
                {(['PASS', 'DOUBT', 'FAIL', 'HOLD'] as const).map(d => <Bar isAnimationActive={false} key={d} dataKey={d} stackId="a" fill={decisionColor[d]} />)}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>
        <Panel title="Open alerts" aside={<span className="text-mist text-sm num">{o.station.alertsOpen} open</span>}>
          {o.alerts.length ? (
            <ul className="space-y-2 max-h-56 overflow-auto">
              {o.alerts.slice().reverse().map(a => (
                <li key={a.id} className="text-sm border-l-2 pl-3" style={{ borderColor: a.severity === 'CRITICAL' ? 'var(--fail)' : a.severity === 'WARNING' ? 'var(--doubt)' : 'var(--mist)' }}>
                  <div className="font-semibold">{a.title} <span className="text-mist font-normal text-xs">· {a.category.toLowerCase()} · {a.created.slice(11)}</span></div>
                  <div className="text-mist text-xs">{a.message}</div>
                </li>
              ))}
            </ul>
          ) : <p className="text-mist text-sm">Nothing needs attention.</p>}
        </Panel>
      </div>

      <Panel title="Product lines">
        <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-3">
          {o.products.map(p => {
            const n = Math.max(p.parts, 1);
            return (
              <div key={p.session} className="bg-raised rounded-xl p-3 flex gap-3">
                {p.thumb ? <img src={p.thumb} alt="" className="w-20 h-20 rounded-lg object-cover" /> : <div className="w-20 h-20 rounded-lg bg-line" />}
                <div className="flex-1 min-w-0">
                  <div className="flex justify-between gap-2 items-start">
                    <div className="font-semibold truncate">{p.name.replace(/^\d+/, '')}</div>
                    {p.alarm ? <Chip tone="var(--doubt)">conditions changed</Chip> : <Chip tone="var(--pass)">{p.stage.toLowerCase()}</Chip>}
                  </div>
                  <div className="text-xs text-mist">{p.source} · {p.plant} · {p.parts} parts</div>
                  <div className="flex h-2 rounded-full overflow-hidden mt-2 bg-line" aria-label="Decision mix">
                    {(['pass', 'doubt', 'fail', 'hold'] as const).map(k => <div key={k} style={{ width: `${(100 * p[k]) / n}%`, background: decisionColor[k.toUpperCase() as 'PASS'] }} />)}
                  </div>
                  <div className="flex gap-3 text-[11px] text-mist mt-1 num"><span>{p.pass} pass</span><span>{p.doubt} doubt</span><span>{p.fail} fail</span>{p.hold > 0 && <span>{p.hold} hold</span>}</div>
                  <button onClick={() => { setSessionId(p.session); setAct('line'); }} className="text-doubt text-xs mt-1">Open the line →</button>
                </div>
              </div>
            );
          })}
        </div>
      </Panel>

      <Panel title="Latest decisions" aside={<Btn tone="ghost" onClick={() => setAct('history')}>Full history</Btn>}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm num">
            <thead className="text-mist text-xs text-left"><tr><th className="py-1">Part</th><th>Product</th><th>Decision</th><th>Reason</th><th>Unusualness</th><th>Time</th></tr></thead>
            <tbody>
              {o.recent.slice().reverse().map(r => (
                <tr key={r.id} className="border-t border-line hover:bg-raised cursor-pointer" onClick={() => setPass(r.id)}>
                  <td className="py-1.5 flex items-center gap-2"><img src={r.image} alt="" className="w-8 h-8 rounded object-cover" />{r.id}</td>
                  <td>{r.product.replace(/^\d+/, '')}</td><td><DecisionPill d={r.decision} /></td>
                  <td className="text-mist text-xs max-w-[220px] truncate">{r.reason ?? '—'}</td><td>{r.score.toFixed(3)}</td><td className="text-mist">{r.created.slice(11)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      {pass && <PassportModal rid={pass} onClose={() => setPass(null)} />}
    </div>
  );
}
