import React from 'react';
import { api } from '../api';
import { useStore } from '../store';
import { Panel, pct } from '../ui/bits';
import { Kpi, PageHead, can, usePoll } from '../room/common';
import { BarList, LinePicker, Measured, prettyStatus, useSid } from './common';

export default function Quality() {
  const [sid, setSid] = useSid();
  const { role, setError } = useStore();
  const [o, reload] = usePoll(() => (sid ? api.smtLine(sid) : Promise.resolve(null)), 10000, [sid]);
  if (!o) return <PageHead title="Quality" sub="Loading…" />;
  const m = o.metrics;
  const qm = can(role, 'QUALITY_MANAGER', 'ADMIN');
  const setClass = async (k: number) => { try { await api.setIpc(sid!, k); reload(); } catch (e: any) { setError(e.message); } };
  const d = m.dpmo;
  return (
    <div className="space-y-5">
      <PageHead title="Quality" sub="The numbers an electronics plant is run on, computed from real inspected boards (fault-lab boards excluded): first-pass yield, false calls, escapes, IPC-7912-style DPMO, and where the faults concentrate."
        aside={<div className="flex gap-2 items-center"><LinePicker sid={sid} setSid={setSid} /><Measured /></div>} />
      <Panel title="Acceptance standard" aside={!qm ? <span className="text-xs text-mist">quality manager sets this</span> : undefined}>
        <div className="flex flex-wrap gap-2">
          {[1, 2, 3].map(k => (
            <button key={k} disabled={!qm} onClick={() => setClass(k)}
              className={`rounded-xl px-3 py-2 text-left text-sm border ${m.ipcClass === k ? 'border-doubt bg-raised' : 'border-line'} disabled:cursor-not-allowed`}>
              <div className="font-semibold">IPC-A-610 Class {k}</div><div className="text-xs text-mist">{m.ipcClasses[k].split(' - ')[1]}</div>
            </button>
          ))}
        </div>
        <p className="text-xs text-mist mt-2">Placement shifts are graded with the published side-overhang limits (50% of the part's width for Class 1-2, 25% for Class 3; end overhang never). IPC-inspired grading, not a certified IPC inspection.</p>
      </Panel>
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3">
        <Kpi label="Boards" value={m.boards} />
        <Kpi label="First-pass yield" value={m.firstPassYield == null ? '—' : pct(m.firstPassYield)} tone="var(--pass)" />
        <Kpi label="False-call rate" value={m.falseCallRate == null ? '—' : pct(m.falseCallRate)} sub="flagged boards that were good" />
        <Kpi label="Escapes" value={m.escapes} tone={m.escapes ? 'var(--fail)' : undefined} />
        <Kpi label="DPMO index" value={d.index ?? '—'} />
        <Kpi label="Component DPMO" value={d.component ?? '—'} sub={`${d.defects.component} / ${d.opportunities.component.toLocaleString()}`} />
        <Kpi label="Placement DPMO" value={d.placement ?? '—'} sub={`${d.defects.placement} / ${d.opportunities.placement.toLocaleString()}`} />
        <Kpi label="Termination DPMO" value={d.termination ?? '—'} sub={`${d.defects.termination} / ${d.opportunities.termination.toLocaleString()}`} />
      </div>
      <p className="text-xs text-mist -mt-2">DPMO = defects / opportunities × 1,000,000 (IPC-7912 style: the bare board counts as one component opportunity; {m.terminationsPerBoard} terminations per board, estimated from part types).</p>
      <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-5">
        <Panel title="Which parts fail (reference designator)"><BarList rows={m.pareto.reference} /></Panel>
        <Panel title="Which part types fail"><BarList rows={m.pareto.kind} color="var(--doubt)" /></Panel>
        <Panel title="What goes wrong"><BarList rows={m.pareto.status} fmt={prettyStatus} /></Panel>
        <Panel title="Where it started (line station)"><BarList rows={m.pareto.stage.map((x: any) => [x[1], x[2]])} color="var(--hold)" /></Panel>
        <Panel title={`IPC-A-610 Class ${m.ipcClass} verdicts`}><BarList rows={m.pareto.ipc} color="var(--fail)" /></Panel>
      </div>
    </div>
  );
}
