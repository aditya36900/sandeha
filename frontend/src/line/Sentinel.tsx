import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { api } from '../api';
import { useStore } from '../store';
import { Btn, Panel, Voice, decisionColor, pct } from '../ui/bits';
import { Kpi, PageHead, usePoll } from '../room/common';
import { LinePicker, Measured, useSid } from './common';

const tone = (v: number | null) => (v == null ? 'var(--mist)' : v >= 0.8 ? 'var(--pass)' : v >= 0.5 ? 'var(--doubt)' : 'var(--fail)');

/** Sentinel: the station audits itself live by planting known faults and keeping score. */
export default function Sentinel() {
  const [sid, setSid] = useSid();
  const { setAct, setSelectedRecord, setError, role } = useStore();
  const [r, reload] = usePoll(() => (sid ? api.sentinel(sid) : Promise.resolve(null)), 5000, [sid]);
  const [busy, setBusy] = useState(false);
  const run = async (n: number) => {
    if (!sid) return;
    setBusy(true);
    try { await api.sentinelRun(sid, n); reload(); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  if (!r) return <PageHead title="Sentinel" sub="Loading…" />;
  const kinds = Object.entries(r.kinds) as [string, any][];
  return (
    <div className="space-y-4">
      <PageHead title="Sentinel: the station audits itself" sub="Every 5 real boards it plants one known fault on a held-out good board and inspects it like any other. The catch rate below is measured on this line as it is right now. No AOI brochure gives you that; this page updates while you watch."
        aside={<div className="flex gap-2 items-center"><LinePicker sid={sid} setSid={setSid} /><Measured /></div>} />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi label="Planted faults audited" value={r.audits} sub={`one every ${r.everyNBoards} real boards · ${r.realBoards} real so far`} />
        <Kpi label="Stopped (not passed)" value={r.overallStopped == null ? '—' : pct(r.overallStopped, 0)} tone={tone(r.overallStopped)} sub="all audits" />
        <Kpi label="Located (right part named)" value={r.overallLocated == null ? '—' : pct(r.overallLocated, 0)} tone={tone(r.overallLocated)} sub="all audits" />
        <Kpi label="Weakest right now" value={r.weakest ? r.kinds[r.weakest].title : '—'} tone={r.weakest ? tone(r.kinds[r.weakest].stopped) : undefined} sub={r.weakest ? `${pct(r.kinds[r.weakest].stopped, 0)} stopped in the last ${r.kinds[r.weakest].recentN}` : 'needs 3 audits per kind'} />
      </div>
      <Panel title="Live catch rate by fault type" aside={
        <div className="flex gap-2 items-center">
          <span className="text-xs text-mist">last {r.window} per type</span>
          <Btn tone="accent" disabled={busy || !r.boardReady} onClick={() => run(6)}>{busy ? 'Planting and inspecting…' : 'Audit 6 now'}</Btn>
          {(role === 'QUALITY_MANAGER' || role === 'ADMIN') && <Btn tone="ghost" disabled={busy} onClick={async () => { if (!sid) return; try { await api.sentinelReset(sid); reload(); } catch (e: any) { setError(e.message); } }}>Reset history</Btn>}
        </div>}>
        {!r.boardReady && <p className="text-mist text-sm">The component map is still being built; audits start when it is ready.</p>}
        <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
          {kinds.map(([k, v]) => (
            <div key={k} className="panel p-3">
              <div className="flex justify-between items-baseline">
                <span className="font-medium">{v.title}</span>
                <span className="num text-xl" style={{ color: tone(v.stopped) }}>{v.stopped == null ? '—' : pct(v.stopped, 0)}</span>
              </div>
              <div className="text-xs text-mist">stopped · located {v.located == null ? '—' : pct(v.located, 0)} · {v.recentN} recent, {v.n} total</div>
              <div className="flex gap-[2px] mt-2 h-3">
                {v.trail.length ? v.trail.map((x: number, i: number) => (
                  <motion.i key={i} initial={{ scaleY: 0 }} animate={{ scaleY: 1 }} className="flex-1 rounded-[2px]" style={{ background: x ? 'var(--pass)' : 'var(--fail)', transformOrigin: 'bottom' }} title={x ? 'stopped' : 'missed'} />
                )) : <span className="text-[11px] text-mist">no audits yet</span>}
              </div>
              {k === 'solder_dry' && <div className="text-[11px] text-doubt mt-1">Dry joints are not visible from one top-down camera; this number is the proof.</div>}
            </div>
          ))}
        </div>
      </Panel>
      <div className="grid xl:grid-cols-[1fr_1.2fr] gap-4">
        <Panel title="Why this matters">
          <Voice>A pass is only worth something if the inspector is still awake.</Voice>
          <ul className="text-sm list-disc pl-5 mt-3 space-y-1.5">
            <li>A lens fogs, a lamp dims, a camera gets nudged: real defects start slipping through. With Sentinel the <b>planted</b> faults slip first, and the station raises an alarm before a customer finds the escape.</li>
            <li>The numbers are per fault type, so you know what this line can and cannot see today, not what a brochure claims.</li>
            <li>Audited boards are marked synthetic: they never touch yield, DPMO, the approval queue or the cost figures.</li>
            <li>Alarm rule: a type that was stopped ≥ 60% of the time in its first 8 audits and drops by 40 points in the last 8.</li>
          </ul>
        </Panel>
        <Panel title="Recent audits">
          <div className="overflow-x-auto max-h-80">
            <table className="w-full text-sm num">
              <thead className="text-mist text-xs text-left"><tr><th className="py-1">Time</th><th>Planted</th><th>On</th><th>Verdict</th><th>Located</th><th>ms</th></tr></thead>
              <tbody>
                {r.recent.map((a: any) => (
                  <tr key={a.part} className="border-t border-line hover:bg-raised cursor-pointer" onClick={() => { setSelectedRecord(a.part); setAct('approval'); }}>
                    <td className="py-1 text-mist text-xs">{a.t.slice(11)}</td><td>{r.kinds[a.kind].title}</td><td>{a.component} <span className="text-mist text-xs">{a.compKind}</span></td>
                    <td><span style={{ color: a.stopped ? decisionColor[a.decision as 'FAIL'] : 'var(--fail)' }}>{a.stopped ? a.decision : 'PASSED (missed)'}</span></td>
                    <td>{a.located ? <span className="text-pass">yes · {a.status?.toLowerCase().replace('_', ' ')}</span> : <span className="text-mist">no</span>}</td><td className="text-mist">{a.ms}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!r.recent.length && <p className="text-mist text-sm">No audits yet. Scan boards on the line, or press "Audit 6 now".</p>}
          </div>
        </Panel>
      </div>
      <p className="text-xs text-mist">{r.note}</p>
    </div>
  );
}
