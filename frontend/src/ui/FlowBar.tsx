import React, { useEffect, useState } from 'react';
import { api } from '../api';
import { Act, useStore } from '../store';

export const JOURNEY: { id: Act; title: string; hint: string }[] = [
  { id: 'choose', title: 'Choose a board', hint: 'pick a circuit board or bring your own' },
  { id: 'genesis', title: 'Learn it', hint: '30 good boards, every component mapped' },
  { id: 'interview', title: 'Answer questions', hint: 'what I am unsure about before I start' },
  { id: 'line', title: 'Scan boards', hint: 'unlabelled boards, checked part by part' },
  { id: 'approval', title: 'Approve', hint: 'a person signs off doubts and rejects' },
  { id: 'rework', title: 'Rework', hint: 'repair tickets for rejected boards' },
  { id: 'quality', title: 'Quality report', hint: 'yield, DPMO, false calls, where faults start' },
];

/** The journey, always visible: where you are, what has happened at each step, and what to do next. */
export default function FlowBar() {
  const { act, setAct, sessionId, view } = useStore();
  const [waiting, setWaiting] = useState<number | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const n = view?.records.length ?? 0;
  useEffect(() => {
    if (!sessionId) return;
    let live = true;
    const load = () => {
      api.approvalQueue(sessionId).then(q => live && setWaiting(q.length)).catch(() => {});
      api.rework(sessionId).then(t => live && setOpen(t.filter(x => x.status === 'OPEN').length)).catch(() => {});
    };
    load();
    const t = setInterval(load, 8000);
    return () => { live = false; clearInterval(t); };
  }, [sessionId, Math.floor(n / 3)]);
  const stage = view?.stage;
  const status: Record<string, string> = {
    choose: sessionId ? (view?.summary?.displayName ?? view?.summary?.name ?? 'chosen') : 'start here',
    genesis: stage && stage !== 'CREATED' && stage !== 'GENESIS' ? 'learned' : stage === 'GENESIS' ? 'learning…' : '',
    interview: (view?.questions?.length ?? 0) ? `${view!.questions.length} questions` : '',
    line: n ? `${n} boards` : '',
    approval: waiting == null ? '' : waiting ? `${waiting} waiting` : 'all signed off',
    rework: open == null ? '' : open ? `${open} open` : 'none open',
    quality: n ? 'ready' : '',
  };
  const idx = JOURNEY.findIndex(j => j.id === act);
  const next = (() => {
    if (!sessionId) return { to: 'choose' as Act, text: 'Choose a board to start' };
    if (stage === 'GENESIS' || stage === 'CREATED') return { to: 'genesis' as Act, text: 'Watch it learn the board' };
    if (!n) return { to: 'line' as Act, text: 'Scan your first boards' };
    if (waiting) return { to: 'approval' as Act, text: `Approve ${waiting} board${waiting === 1 ? '' : 's'} waiting for a person` };
    if (open) return { to: 'rework' as Act, text: `Close ${open} repair ticket${open === 1 ? '' : 's'}` };
    if (act !== 'quality') return { to: 'quality' as Act, text: 'Read the quality report' };
    return { to: 'line' as Act, text: 'Scan more boards' };
  })();
  return (
    <nav className="mt-3 rounded-2xl bg-surface p-2 flex flex-wrap items-center gap-1" aria-label="Journey">
      <ol className="flex flex-1 min-w-0 overflow-x-auto gap-1">
        {JOURNEY.map((j, i) => {
          const here = act === j.id;
          const done = idx > i || (!!status[j.id] && !here && i < 4 && !!sessionId);
          return (
            <li key={j.id} className="flex items-center">
              <button disabled={j.id !== 'choose' && !sessionId} onClick={() => setAct(j.id)} title={j.hint}
                className={`flex items-center gap-2 rounded-xl px-2.5 py-1.5 text-left whitespace-nowrap transition disabled:opacity-35 ${here ? 'bg-raised ring-1 ring-doubt' : 'hover:bg-raised/60'}`}>
                <span className={`w-5 h-5 rounded-full grid place-items-center text-[11px] num ${here ? 'bg-doubt text-ink' : done ? 'bg-pass/25 text-pass' : 'bg-line text-mist'}`}>{done && !here ? '✓' : i + 1}</span>
                <span>
                  <span className="block text-[13px] font-semibold leading-tight">{j.title}</span>
                  <span className="block text-[10px] text-mist leading-tight">{status[j.id] || j.hint}</span>
                </span>
              </button>
              {i < JOURNEY.length - 1 && <span className="text-line px-0.5">›</span>}
            </li>
          );
        })}
      </ol>
      {next.to !== act && (
        <button onClick={() => setAct(next.to)} className="ml-auto rounded-xl px-3 py-2 text-sm font-semibold bg-doubt text-ink hover:brightness-110 whitespace-nowrap">
          Next: {next.text} →
        </button>
      )}
    </nav>
  );
}
