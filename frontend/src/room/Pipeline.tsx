import React, { useEffect, useState } from 'react';
import { api, Trace } from '../api';
import { useStore } from '../store';
import { Panel, Verdict } from '../ui/bits';
import { PageHead, SessionPicker } from './common';

const fmt = (v: any): string => {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') return Number.isInteger(v) ? v.toLocaleString() : v.toFixed(4);
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (typeof v === 'object') return Object.entries(v).map(([k, x]) => `${k} ${fmt(x)}`).join(' · ');
  return String(v);
};

/** One real part walked through every stage, with the actual intermediate images and numbers. */
export default function Pipeline() {
  const { sessionId, setSessionId, views, selectedRecord } = useStore();
  const [pick, setSid] = useState<string | null>(null);
  // follow the open product line until the user picks one (sessions may still be restoring at mount)
  const sid = pick ?? sessionId ?? Object.keys(views).find(k => views[k].summary) ?? null;
  const recs = (sid && views[sid]?.records) || [];
  const [rid, setRid] = useState<string | null>(selectedRecord);
  const [t, setT] = useState<Trace | null>(null);
  const [open, setOpen] = useState<string>('compare');
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { if (!rid || !recs.find(r => r.id === rid)) setRid(recs[recs.length - 1]?.id ?? null); }, [sid, recs.length]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!sid || !rid) return;
    setErr(null);
    api.trace(sid, rid).then(setT).catch(e => setErr(e.message));
  }, [sid, rid]);
  const rec = t?.record;
  const timing = (k: string) => {
    const m = t?.timings || {};
    return k === 'see' ? m.see : k === 'compare' || k === 'understand' ? m['understand+compare'] : k === 'locate' ? m.regions : k === 'decide' || k === 'doubt' ? m['doubt+decide'] : undefined;
  };
  return (
    <div className="space-y-5">
      <PageHead title="Pipeline" sub="Pick any inspected part and see exactly what each stage computed for it, with real images and numbers, not a diagram."
        aside={<div className="flex gap-2">
          <SessionPicker value={sid} onChange={id => { setSid(id); if (id) setSessionId(id); }} />
          <select value={rid ?? ''} onChange={e => setRid(e.target.value)} className="bg-raised rounded-lg px-3 py-1.5 text-sm num" aria-label="Part">
            {recs.slice().reverse().slice(0, 200).map(r => <option key={r.id} value={r.id}>{r.id} · {r.decision}</option>)}
          </select>
        </div>} />
      {err && <p className="text-fail">{err}</p>}
      {!recs.length && <Panel><p className="text-mist">No parts inspected on this line yet. Scan some on "Run the line".</p></Panel>}
      {t && rec && (
        <>
          <div className="flex items-baseline gap-4 flex-wrap">
            <Verdict d={rec.decision} size="xl" />
            <span className="text-mist num">{rec.id} · total {t.latencyMs ?? '—'} ms on this station</span>
          </div>
          <ol className="grid sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-8 gap-3">
            {t.stages.map((s, i) => (
              <li key={s.key}>
                <button onClick={() => setOpen(s.key)} className={`w-full text-left rounded-2xl p-3 h-full border transition ${open === s.key ? 'bg-raised border-doubt' : 'bg-surface border-transparent hover:border-line'}`}>
                  <div className="flex justify-between text-xs text-mist num"><span>{i + 1}</span><span>{timing(s.key) != null ? `${Math.round(timing(s.key)!)} ms` : ''}</span></div>
                  <div className="font-semibold mt-0.5">{s.title}</div>
                  {s.image ? <img src={s.image} alt="" className="mt-2 rounded-lg aspect-square object-cover w-full" /> : <div className="mt-2 rounded-lg aspect-square bg-ink/50 grid place-items-center text-mist text-xs p-2 text-center">{s.what}</div>}
                </button>
              </li>
            ))}
          </ol>
          {(() => {
            const s = t.stages.find(x => x.key === open) ?? t.stages[0];
            return (
              <Panel title={s.title}>
                <p className="text-mist mb-3">{s.what}</p>
                <div className="grid md:grid-cols-[minmax(0,360px)_1fr] gap-5">
                  {s.image ? <img src={s.image} alt="" className="rounded-xl w-full" /> : <div />}
                  <dl className="grid sm:grid-cols-2 gap-x-6 gap-y-2 text-sm num content-start">
                    {Object.entries(s.facts).map(([k, v]) => <div key={k}><dt className="text-mist text-xs">{k}</dt><dd className="break-words">{fmt(v)}</dd></div>)}
                  </dl>
                </div>
              </Panel>
            );
          })()}
          <Panel title="In plain words"><p className="voice text-xl">{rec.explanation}</p></Panel>
        </>
      )}
    </div>
  );
}
