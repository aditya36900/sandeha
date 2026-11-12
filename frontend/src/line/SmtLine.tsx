import React, { useState } from 'react';
import { CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../api';
import { useStore } from '../store';
import { Panel, decisionColor, pct } from '../ui/bits';
import { STATUS_COLOR } from '../ui/Board3D';
import { Kpi, PageHead, usePoll } from '../room/common';
import { LinePicker, Measured, Simulated, prettyStatus, useSid } from './common';

export default function SmtLine() {
  const [sid, setSid] = useSid();
  const { setAct, setSelectedRecord } = useStore();
  const [o] = usePoll(() => (sid ? api.smtLine(sid) : Promise.resolve(null)), 8000, [sid]);
  const [stage, setStage] = useState<string>('aoi_post');
  if (!o) return <PageHead title="The SMT line" sub="Loading…" />;
  const m = o.metrics;
  const roots = Object.entries(o.root as Record<string, any>).filter(([, v]) => v.stage === stage);
  return (
    <div className="space-y-5">
      <PageHead title="The SMT line" sub="Where this station sits on a surface-mount line, and where each fault it finds most likely started, so the fix goes to the right machine, not just the board."
        aside={<LinePicker sid={sid} setSid={setSid} />} />
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3">
        <Kpi label="Boards checked" value={m.boards} sub={`${m.components} components each`} />
        <Kpi label="First-pass yield" value={m.firstPassYield == null ? '—' : pct(m.firstPassYield)} tone="var(--pass)" />
        <Kpi label="DPMO index" value={m.dpmo.index ?? '—'} sub="IPC-7912 style" />
        <Kpi label="False calls" value={m.falseCallRate == null ? '—' : pct(m.falseCallRate)} sub={`${m.falseCalls} of ${m.flagged} flagged boards`} />
        <Kpi label="Escapes" value={m.escapes} tone={m.escapes ? 'var(--fail)' : undefined} sub="defective boards passed" />
        <Kpi label="Fault-lab boards" value={m.synthetic} sub="kept out of these numbers" />
      </div>

      <Panel title="Line flow" aside={<span className="flex gap-2"><Measured /><span className="text-xs text-mist">fault counts attributed to the station they most likely came from</span></span>}>
        <ol className="flex gap-2 overflow-x-auto pb-2">
          {o.stages.map((st: any, i: number) => (
            <li key={st.key} className="flex items-center gap-2 shrink-0">
              <button onClick={() => setStage(st.key)}
                className={`w-36 text-left rounded-xl p-3 border transition ${stage === st.key ? 'border-doubt bg-raised' : st.kind === 'this' ? 'border-pass bg-raised/70' : 'border-line bg-raised/40 hover:border-mist'}`}>
                <div className="text-[10px] text-mist num">{i + 1}</div>
                <div className="font-semibold text-sm leading-tight">{st.title}</div>
                <div className={`text-2xl num mt-1 ${st.faults ? 'text-fail' : 'text-mist'}`}>{st.faults}</div>
                <div className="text-[10px] text-mist">{st.kind === 'this' ? 'this station' : 'faults traced here'}</div>
              </button>
              {i < o.stages.length - 1 && <span className="text-mist">→</span>}
            </li>
          ))}
        </ol>
        <div className="mt-3 grid md:grid-cols-[1fr_1.4fr] gap-4">
          <div className="rounded-xl bg-raised p-3 text-sm">
            <div className="font-semibold">{o.stages.find((x: any) => x.key === stage)?.title}</div>
            <p className="text-mist">{o.stages.find((x: any) => x.key === stage)?.what}</p>
          </div>
          <div className="text-sm space-y-2">
            {roots.length ? roots.map(([k, v]: [string, any]) => (
              <div key={k} className="rounded-xl p-3 border border-line">
                <div className="font-semibold" style={{ color: STATUS_COLOR[k] }}>{prettyStatus(k)} → {v.origin}</div>
                <div className="text-mist text-xs">usual cause: {v.cause}</div>
                <div className="text-xs mt-1">check: {v.check}</div>
              </div>
            )) : <p className="text-mist">No fault type traces back to this station.</p>}
          </div>
        </div>
      </Panel>

      <div className="grid xl:grid-cols-2 gap-5">
        <Panel title="Latest boards with component faults">
          {!o.recent.length && <p className="text-mist text-sm">None yet.</p>}
          <ul className="space-y-2">
            {o.recent.map((b: any) => (
              <li key={b.part}>
                <button onClick={() => { setSelectedRecord(b.part); setAct('approval'); }} className="w-full flex gap-3 items-start text-left rounded-xl p-2 hover:bg-raised">
                  <img src={b.image} alt="" className="w-14 h-14 rounded-lg object-cover" />
                  <div className="text-xs min-w-0">
                    <div className="font-semibold text-sm"><span style={{ color: decisionColor[b.decision as 'PASS'] }}>{b.decision}</span> <span className="num text-mist">{b.part}</span>{b.synthetic && <span className="text-doubt"> · fault lab</span>}</div>
                    {b.faults.map((f: any) => <div key={f.id}><b style={{ color: STATUS_COLOR[f.status] }}>{f.id}</b> {prettyStatus(f.status)} → <span className="text-mist">{f.origin}</span></div>)}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </Panel>
        <Panel title="Reflow profile (SAC305 lead-free)" aside={<Simulated>oven data</Simulated>}>
          <div className="h-56">
            <ResponsiveContainer>
              <LineChart data={o.reflow.points} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
                <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" />
                <XAxis dataKey="t" unit="s" tick={{ fill: 'var(--mist)', fontSize: 11 }} />
                <YAxis unit="°" domain={[0, 270]} tick={{ fill: 'var(--mist)', fontSize: 11 }} />
                <ReferenceArea y1={150} y2={185} fill="var(--doubt)" fillOpacity={0.08} />
                <ReferenceLine y={o.reflow.liquidus} stroke="var(--fail)" strokeDasharray="4 4" label={{ value: 'liquidus 217 °C', fill: 'var(--mist)', fontSize: 10, position: 'insideTopRight' }} />
                <Tooltip contentStyle={{ background: 'var(--surface)', border: 'none', borderRadius: 12 }} />
                <Line dataKey="temp" stroke="var(--doubt)" strokeWidth={2.5} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="grid grid-cols-2 gap-2 mt-2 text-xs">
            {o.reflow.checks.map((c: any) => (
              <div key={c.name} className="flex justify-between gap-2 rounded-lg bg-raised px-2 py-1"><span>{c.name}</span><span className={c.ok ? 'text-pass' : 'text-fail'}>{c.value} <span className="text-mist">({c.spec})</span></span></div>
            ))}
          </div>
          <p className="text-[11px] text-mist mt-2">{o.reflow.note}</p>
        </Panel>
      </div>
    </div>
  );
}
