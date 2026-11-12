import React, { useEffect, useState } from 'react';
import { api, BoardMapT } from '../api';
import { useStore } from '../store';
import { SessionPicker } from '../room/common';

/** The product line these pages look at: the open one, or the first electronics line. */
export function useSid(): [string | null, (s: string | null) => void] {
  const { sessionId, setSessionId, views } = useStore();
  const [pick, setPick] = useState<string | null>(null);
  const sid = pick ?? sessionId ?? Object.keys(views).find(k => views[k].summary && views[k].summary!.source !== 'MAD-Sim') ?? null;
  return [sid, (s: string | null) => { setPick(s); if (s) setSessionId(s); }];
}

export function useBoardMap(sid: string | null): BoardMapT | null {
  const [b, setB] = useState<BoardMapT | null>(null);
  useEffect(() => {
    if (!sid) return;
    let live = true;
    let t: ReturnType<typeof setTimeout> | undefined;
    const load = () => api.board(sid).then(x => { if (!live) return; setB(x); if (x.status === 'building') t = setTimeout(load, 5000); }).catch(() => {});
    load();
    return () => { live = false; if (t) clearTimeout(t); };
  }, [sid]);
  return b;
}

export function LinePicker({ sid, setSid }: { sid: string | null; setSid: (s: string | null) => void }) {
  return <SessionPicker value={sid} onChange={setSid} />;
}

export function Simulated({ children }: { children?: React.ReactNode }) {
  return <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded border border-doubt text-doubt" title="Line context this station cannot measure from a camera">simulated{children ? ` · ${children}` : ''}</span>;
}

export function Measured() {
  return <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded border border-pass text-pass" title="Computed from boards this station inspected">measured</span>;
}

export function BarList({ rows, color = 'var(--fail)', fmt }: { rows: [string, number][]; color?: string; fmt?: (k: string) => string }) {
  const max = Math.max(1, ...rows.map(r => r[1]));
  if (!rows.length) return <p className="text-mist text-sm">Nothing yet.</p>;
  return (
    <ul className="space-y-1.5">
      {rows.map(([k, v]) => (
        <li key={k} className="text-sm">
          <div className="flex justify-between gap-3"><span className="truncate">{fmt ? fmt(k) : k}</span><span className="num text-mist">{v}</span></div>
          <div className="h-1.5 bg-line rounded-full"><div className="h-full rounded-full" style={{ width: `${(100 * v) / max}%`, background: color }} /></div>
        </li>
      ))}
    </ul>
  );
}

export const prettyStatus = (s: string) => s.toLowerCase().replace('_', ' ');
