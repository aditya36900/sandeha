import React from 'react';
import { api } from '../api';
import { useStore } from '../store';
import { Btn, Panel } from '../ui/bits';
import { STATUS_COLOR } from '../ui/Board3D';
import { Chip, PageHead, can, usePoll } from '../room/common';
import { LinePicker, prettyStatus, useSid } from './common';

const OUT: Record<string, string> = { OPEN: 'var(--doubt)', REPAIRED: 'var(--pass)', SCRAPPED: 'var(--fail)', NO_FAULT_FOUND: 'var(--hold)' };

export default function Rework() {
  const [sid, setSid] = useSid();
  const { role, setError, setAct, setSelectedRecord, notify } = useStore();
  const [t, reload] = usePoll(() => (sid ? api.rework(sid) : Promise.resolve([])), 8000, [sid]);
  const tech = can(role, 'INSPECTOR', 'QUALITY_MANAGER', 'ADMIN');
  const close = async (rid: string, outcome: string) => {
    try { await api.closeRework(sid!, rid, outcome); reload(); notify(`Ticket ${rid.split('-').pop()} closed: ${outcome.replace(/_/g, ' ').toLowerCase()}. It now counts in the quality report.`, outcome === 'SCRAPPED' ? 'fail' : 'pass'); }
    catch (e: any) { setError(e.message); }
  };
  const open = (t ?? []).filter(x => x.status === 'OPEN');
  const done = (t ?? []).filter(x => x.status !== 'OPEN');
  const Card = ({ x }: { x: any }) => (
    <li className="rounded-xl bg-raised p-3 flex gap-3 flex-wrap">
      <button onClick={() => { setSelectedRecord(x.part); setAct('approval'); }} aria-label="Open dossier"><img src={x.heat} alt="" className="w-24 h-24 rounded-lg object-cover" /></button>
      <div className="flex-1 min-w-[240px] text-sm">
        <div className="flex gap-2 items-center flex-wrap"><b className="num">{x.part}</b><Chip tone={OUT[x.status]}>{x.status.replace(/_/g, ' ').toLowerCase()}</Chip>{x.synthetic && <Chip tone="var(--doubt)">fault lab</Chip>}
          {x.by && <span className="text-xs text-mist">by {x.by} · {x.closed}</span>}</div>
        <ol className="mt-1 space-y-0.5 list-decimal pl-5">
          {x.actions.map((a: any) => <li key={a.id}><span style={{ color: STATUS_COLOR[a.status] }}>{a.action}</span> <span className="text-xs text-mist">({prettyStatus(a.status)} · IPC {a.ipc})</span></li>)}
        </ol>
      </div>
      {x.status === 'OPEN' && (
        <div className="flex flex-col gap-1.5">
          <Btn tone="pass" disabled={!tech} onClick={() => close(x.part, 'REPAIRED')}>Repaired</Btn>
          <Btn tone="ghost" disabled={!tech} onClick={() => close(x.part, 'NO_FAULT_FOUND')}>No fault found</Btn>
          <Btn tone="fail" disabled={!tech} onClick={() => close(x.part, 'SCRAPPED')}>Scrap</Btn>
        </div>
      )}
    </li>
  );
  return (
    <div className="space-y-5">
      <PageHead title="Rework" sub="Every rejected board becomes a repair ticket with the exact actions per component. A technician's 'no fault found' is recorded as evidence of a false call."
        aside={<LinePicker sid={sid} setSid={setSid} />} />
      {!tech && <p className="text-sm text-mist">Switch to an inspector (or above) to close tickets.</p>}
      <Panel title={`Open (${open.length})`}>{open.length ? <ul className="space-y-3">{open.map(x => <Card key={x.part} x={x} />)}</ul> : <p className="text-mist text-sm">No open tickets.</p>}</Panel>
      <Panel title={`Closed (${done.length})`}>{done.length ? <ul className="space-y-3">{done.map(x => <Card key={x.part} x={x} />)}</ul> : <p className="text-mist text-sm">Nothing closed yet.</p>}</Panel>
    </div>
  );
}
