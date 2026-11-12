import React, { useState } from 'react';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../api';
import { useStore } from '../store';
import { Panel, decisionColor, pct, reasonText } from '../ui/bits';
import { PageHead, PassportModal, SessionPicker, usePoll } from './common';

const tip = { contentStyle: { background: 'var(--surface)', border: 'none', borderRadius: 12 }, cursor: { fill: 'var(--raised)' } };
const axis = { tick: { fill: 'var(--mist)', fontSize: 11 } };

function Bars({ data }: { data: Record<string, number> }) {
  const rows = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...rows.map(r => r[1]));
  if (!rows.length) return <p className="text-mist text-sm">None yet.</p>;
  return (
    <ul className="space-y-1.5">
      {rows.map(([k, v]) => (
        <li key={k} className="text-sm">
          <div className="flex justify-between"><span>{reasonText[k] ?? k}</span><span className="num text-mist">{v}</span></div>
          <div className="h-1.5 bg-line rounded-full"><div className="h-full rounded-full bg-doubt" style={{ width: `${(100 * v) / max}%` }} /></div>
        </li>
      ))}
    </ul>
  );
}

export default function Analytics() {
  const { sessionId } = useStore();
  const [sid, setSid] = useState<string | null>(sessionId);
  const [a] = usePoll(() => api.analytics(sid), 10000, [sid]);
  const [pass, setPass] = useState<string | null>(null);
  return (
    <div className="space-y-5">
      <PageHead title="Analytics" sub="Which defects we catch, which we ask about, which slip, where on the part they sit, and how changed conditions move the numbers."
        aside={<SessionPicker value={sid} onChange={setSid} all />} />
      {a && (
        <>
          <div className="grid xl:grid-cols-[minmax(0,1fr)_380px] gap-5">
            <Panel title="Defect types: what happened to every truly defective part">
              {a.pareto.length ? (
                <div className="h-72">
                  <ResponsiveContainer>
                    <BarChart data={a.pareto.slice(0, 12)} margin={{ top: 8, right: 8, bottom: 30, left: -18 }}>
                      <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" vertical={false} />
                      <XAxis dataKey="type" {...axis} angle={-25} textAnchor="end" interval={0} />
                      <YAxis allowDecimals={false} {...axis} />
                      <Tooltip {...tip} />
                      <Legend verticalAlign="top" />
                      <Bar isAnimationActive={false} name="rejected" dataKey="caught" stackId="a" fill={decisionColor.FAIL} />
                      <Bar isAnimationActive={false} name="asked a person" dataKey="asked" stackId="a" fill={decisionColor.DOUBT} />
                      <Bar isAnimationActive={false} name="held" dataKey="held" stackId="a" fill={decisionColor.HOLD} />
                      <Bar isAnimationActive={false} name="escaped" dataKey="escaped" stackId="a" fill="var(--bone)" />
                      <Bar isAnimationActive={false} name="typical AI escapes" dataKey="escapedTypicalAI" fill="var(--mist)" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : <p className="text-mist text-sm">No known defects inspected yet.</p>}
            </Panel>
            <Panel title="Where flagged parts were unusual">
              <div className="relative aspect-square rounded-xl overflow-hidden bg-raised">
                {a.productImage && <img src={a.productImage} alt="" className="absolute inset-0 w-full h-full object-cover opacity-60" />}
                {a.spots.map(s => (
                  <button key={s.id} onClick={() => setPass(s.id)} title={`${s.id} · ${s.decision}`} aria-label={`Open ${s.id}`}
                    className="absolute w-3 h-3 -ml-1.5 -mt-1.5 rounded-full ring-2 ring-ink hover:scale-150 transition"
                    style={{ left: `${s.x * 100}%`, top: `${s.y * 100}%`, background: decisionColor[s.decision] }} />
                ))}
                {!a.productImage && <p className="absolute left-2 top-2 text-mist text-[11px]">All lines: pick one to see its photo under the dots</p>}
              </div>
              <p className="text-xs text-mist mt-2">Each dot is the most unusual spot of one rejected or doubted part. Tap a dot for its passport.</p>
            </Panel>
          </div>
          <div className="grid lg:grid-cols-3 gap-5">
            <Panel title="Why I asked a person"><Bars data={a.doubtReasons} /></Panel>
            <Panel title="Why parts were held"><Bars data={a.holdReasons} /></Panel>
            <Panel title="Normal vs changed conditions">
              <table className="w-full text-sm num">
                <thead className="text-mist text-xs text-left"><tr><th /><th>normal ({a.conditions.nNormal})</th><th>changed ({a.conditions.nChanged})</th></tr></thead>
                <tbody>
                  {(['PASS', 'DOUBT', 'FAIL', 'HOLD'] as const).map(d => (
                    <tr key={d} className="border-t border-line"><td className="py-1" style={{ color: decisionColor[d] }}>{d.toLowerCase()}</td><td>{pct(a.conditions.normal[d])}</td><td>{pct(a.conditions.changed[d])}</td></tr>
                  ))}
                </tbody>
              </table>
              <p className="text-xs text-mist mt-2">Under changed light or camera position I stop passing parts on my own, so doubts rise instead of escapes.</p>
            </Panel>
          </div>
          <Panel title="Decisions over time (blocks of 10 parts)">
            <div className="h-56">
              <ResponsiveContainer>
                <BarChart data={a.timeline} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
                  <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" vertical={false} />
                  <XAxis dataKey="block" {...axis} />
                  <YAxis allowDecimals={false} {...axis} />
                  <Tooltip {...tip} />
                  {(['PASS', 'DOUBT', 'FAIL', 'HOLD'] as const).map(d => <Bar isAnimationActive={false} key={d} dataKey={d} stackId="a" fill={decisionColor[d]} />)}
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Panel>
        </>
      )}
      {pass && <PassportModal rid={pass} onClose={() => setPass(null)} />}
    </div>
  );
}
