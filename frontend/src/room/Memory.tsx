import React, { useState } from 'react';
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../api';
import { useStore } from '../store';
import { Btn, Panel } from '../ui/bits';
import { Kpi, PageHead, SessionPicker, usePoll } from './common';

export default function Memory() {
  const { sessionId, setSessionId, setError, views } = useStore();
  const [pick, setSid] = useState<string | null>(null);
  // follow the open product line until the user picks one (sessions may still be restoring at mount)
  const sid = pick ?? sessionId ?? Object.keys(views).find(k => views[k].summary) ?? null;
  const [m, reload] = usePoll(() => (sid ? api.memory(sid) : Promise.resolve(null)), 8000, [sid]);
  const [busy, setBusy] = useState(false);
  const check = async () => {
    if (!sid) return;
    setBusy(true);
    try { await api.forgetting(sid); reload(); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  const f = (m?.forgetting ?? []).map((r, i) => ({ i: i + 1, label: r.label, good: r.goods ? (100 * r.goodsPassed) / r.goods : null, defect: r.defects ? (100 * r.defectsFlagged) / r.defects : null }));
  return (
    <div className="space-y-5">
      <PageHead title="Memory" sub="What this line knows: good-part memories, the defects it has met, what people taught it, and proof that learning never erased anything."
        aside={<SessionPicker value={sid} onChange={id => { setSid(id); if (id) setSessionId(id); }} />} />
      {!m ? <Panel><p className="text-mist">Pick a product line.</p></Panel> : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
            <Kpi label="Good references" value={m.normal.references} />
            <Kpi label="Patch memories" value={m.normal.patchMemories.toLocaleString()} sub="nearest-neighbour bank, never retrained" />
            <Kpi label="Adaptations" value={m.normal.adaptations.length} sub="new conditions added, old kept" />
            <Kpi label="Real defect examples" value={m.defect.real} />
            <Kpi label="Imagined defects" value={m.defect.imagined} sub="used only to place the pass line" />
            <Kpi label="Learned from people" value={m.defect.learned.length + m.normal.learnedGood.length} sub="each needed two agreeing reviewers" />
          </div>
          <div className="grid xl:grid-cols-2 gap-5">
            <Panel title="Taught by two people">
              {m.normal.learnedGood.length + m.defect.learned.length === 0 ? <p className="text-mist text-sm">Nothing yet. Doubts reviewed by two different people end up here.</p> : (
                <div className="flex flex-wrap gap-3">
                  {m.normal.learnedGood.map(g => <figure key={g.id} className="w-24"><img src={g.image} alt="" className="rounded-lg w-24 h-24 object-cover" /><figcaption className="text-[11px] text-pass">good · {g.by}</figcaption></figure>)}
                  {m.defect.learned.map((d, i) => <figure key={i} className="w-24">{d.image ? <img src={d.image} alt="" className="rounded-lg w-24 h-24 object-cover" /> : <div className="w-24 h-24 rounded-lg bg-raised" />}<figcaption className="text-[11px] text-fail truncate">{d.label} · {d.from}</figcaption></figure>)}
                </div>
              )}
            </Panel>
            <Panel title="Waiting for a second reviewer">
              {m.pending.length ? (
                <div className="flex flex-wrap gap-3">
                  {m.pending.map(p => <figure key={p.id} className="w-24"><img src={p.image} alt="" className="rounded-lg w-24 h-24 object-cover" /><figcaption className="text-[11px] text-mist truncate">{p.votes.map(v => `${v.by}: ${v.verdict}`).join(', ')}</figcaption></figure>)}
                </div>
              ) : <p className="text-mist text-sm">No half-reviewed parts. One vote is never enough to change memory.</p>}
              {!!m.defect.hive.length && <p className="text-sm mt-3">From other plants (fingerprints only, no images): {m.defect.hive.map(h => `${h.label} (${h.from})`).join(', ')}</p>}
            </Panel>
          </div>
          <Panel title="Forgetting check" aside={<Btn tone="doubt" disabled={busy} onClick={check}>{busy ? 'Re-testing…' : 'Run it now'}</Btn>}>
            <p className="text-mist text-sm mb-3">A fixed probe set of good and defective parts is re-scored after every adaptation or lesson. If learning ever broke something it knew, these lines would drop.</p>
            {f.length ? (
              <div className="h-56">
                <ResponsiveContainer>
                  <LineChart data={f} margin={{ top: 8, right: 16, bottom: 0, left: -10 }}>
                    <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" />
                    <XAxis dataKey="i" tick={{ fill: 'var(--mist)', fontSize: 11 }} />
                    <YAxis unit="%" domain={[0, 100]} tick={{ fill: 'var(--mist)', fontSize: 11 }} />
                    <Tooltip contentStyle={{ background: 'var(--surface)', border: 'none', borderRadius: 12 }} labelFormatter={i => f[Number(i) - 1]?.label ?? ''} />
                    <Legend />
                    <Line name="good parts still passed" dataKey="good" stroke="var(--pass)" strokeWidth={2.5} />
                    <Line name="defects still caught" dataKey="defect" stroke="var(--fail)" strokeWidth={2.5} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : <p className="text-mist text-sm">No checks yet. Run one.</p>}
          </Panel>
        </>
      )}
    </div>
  );
}
