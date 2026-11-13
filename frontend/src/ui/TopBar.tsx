import React, { useEffect, useState } from 'react';
import { api, Demo, Role } from '../api';
import { Act, THEMES, useStore } from '../store';
import { Btn } from './bits';
import { Modal, can, roleName } from '../room/common';

const ROLES: Role[] = ['OPERATOR', 'INSPECTOR', 'QUALITY_MANAGER', 'ADMIN'];
const SEV: Record<string, string> = { CRITICAL: 'var(--fail)', WARNING: 'var(--doubt)', INFO: 'var(--mist)' };

function AlertsDrawer({ onClose }: { onClose: () => void }) {
  const { alerts, reloadAlerts, setError, role, setSessionId, setAct } = useStore();
  const [showAll, setShowAll] = useState(false);
  const list = alerts.filter(a => showAll || !a.resolved);
  const act = async (fn: () => Promise<unknown>) => { try { await fn(); reloadAlerts(); } catch (e: any) { setError(e.message); } };
  return (
    <div className="fixed inset-0 z-40" onClick={onClose}>
      <aside className="absolute right-0 top-0 h-full w-full max-w-md bg-surface shadow-2xl p-5 overflow-auto" onClick={e => e.stopPropagation()} aria-label="Alerts">
        <div className="flex justify-between items-center mb-3">
          <h2 className="text-xl font-semibold">Alerts</h2>
          <div className="flex gap-3 items-center text-sm">
            <label className="flex items-center gap-1 text-mist"><input type="checkbox" checked={showAll} onChange={e => setShowAll(e.target.checked)} /> resolved too</label>
            <button onClick={onClose} className="text-mist hover:text-bone">Close</button>
          </div>
        </div>
        {!list.length && <p className="text-mist">Nothing needs attention.</p>}
        <ul className="space-y-2">
          {list.map(a => (
            <li key={a.id} className={`rounded-xl p-3 bg-raised border-l-4 ${a.resolved ? 'opacity-50' : ''}`} style={{ borderColor: SEV[a.severity] }}>
              <div className="flex justify-between gap-2"><span className="font-semibold">{a.title}</span><span className="text-[11px] num text-mist">{a.created.slice(11)}</span></div>
              <div className="text-sm text-mist">{a.message}</div>
              <div className="text-[11px] text-mist mt-1">{a.severity.toLowerCase()} · {a.category.toLowerCase()}{a.session ? ` · ${a.session}` : ''}{a.acknowledged ? ` · seen by ${a.acknowledged_by}` : ''}</div>
              {!a.resolved && (
                <div className="flex gap-2 mt-2">
                  {!a.acknowledged && <Btn tone="ghost" onClick={() => act(() => api.ack(a.id))}>I've seen it</Btn>}
                  <Btn tone="ghost" disabled={!can(role, 'INSPECTOR', 'QUALITY_MANAGER', 'ADMIN')} onClick={() => act(() => api.resolveAlert(a.id))}
                    title={can(role, 'INSPECTOR', 'QUALITY_MANAGER', 'ADMIN') ? undefined : 'An inspector or above resolves alerts'}>Resolve</Btn>
                  {a.session && <Btn tone="ghost" onClick={() => { setSessionId(a.session); setAct(a.category === 'HARDWARE' ? 'hardware' : a.category === 'SHIFT' ? 'chaos' : 'line'); onClose(); }}>Go there</Btn>}
                </div>
              )}
            </li>
          ))}
        </ul>
      </aside>
    </div>
  );
}

function DemoModal({ onClose }: { onClose: () => void }) {
  const { sessionId, setAct, setSessionId, setError, refresh } = useStore();
  const [demos, setDemos] = useState<Demo[]>([]);
  const [busy, setBusy] = useState<number | null>(null);
  const [out, setOut] = useState<Record<number, string>>({});
  useEffect(() => { api.demos().then(setDemos).catch(e => setError(e.message)); }, [setError]);
  const run = async (d: Demo) => {
    setBusy(d.n);
    try {
      const r = await api.runDemo(d.n, sessionId);
      setOut(o => ({ ...o, [d.n]: `${r.decision ? `${r.decision}: ` : ''}${r.message}` }));
      if (r.session) { setSessionId(r.session); refresh(r.session).catch(() => {}); }
    } catch (e: any) { setOut(o => ({ ...o, [d.n]: e.message })); } finally { setBusy(null); }
  };
  return (
    <Modal onClose={onClose} title="Judge demo: 8 scenarios on the real engine">
      <p className="text-mist text-sm mb-3">Each button drives the real pipeline on the open product line (no canned results). Run it, then jump to where it shows.</p>
      <ol className="grid md:grid-cols-2 gap-3">
        {demos.map(d => (
          <li key={d.n} className="bg-raised rounded-xl p-3 flex flex-col gap-2">
            <div className="flex gap-2 items-baseline"><span className="text-doubt num font-semibold">{d.n}</span><span className="font-semibold">{d.title}</span></div>
            <div className="text-xs text-mist">expect: {d.expect}</div>
            {out[d.n] && <div className="text-sm voice">{out[d.n]}</div>}
            <div className="flex gap-2 mt-auto">
              <Btn tone="doubt" disabled={busy !== null} onClick={() => run(d)}>{busy === d.n ? 'Running…' : 'Run'}</Btn>
              <Btn tone="ghost" onClick={() => { setAct(d.goTo as Act); onClose(); }}>Show me</Btn>
            </div>
          </li>
        ))}
      </ol>
    </Modal>
  );
}

export default function TopBar() {
  const { station, role, setRole, alerts, theme, setTheme, setError, reloadAlerts } = useStore();
  const [drawer, setDrawer] = useState(false);
  const [demo, setDemo] = useState(false);
  const open = alerts.filter(a => !a.resolved);
  const critical = open.some(a => a.severity === 'CRITICAL');
  const hold = async (on: boolean) => {
    try { await api.hold(on, on ? 'Emergency stop pressed on the dashboard' : ''); reloadAlerts(); } catch (e: any) { setError(e.message); }
  };
  return (
    <>
      <div className="sticky top-0 z-30 -mx-5 lg:-mx-8 px-5 lg:px-8 py-2.5 bg-ink/90 backdrop-blur border-b border-line flex flex-wrap items-center gap-2">
        <span className="font-semibold mr-1">{station?.name ?? 'Station'}</span>
        <span className={`text-xs px-2 py-0.5 rounded-full ${station?.hold ? 'bg-fail text-ink' : station?.faults.length ? 'bg-doubt text-ink' : 'bg-pass/20 text-pass'}`}>
          {station?.hold ? 'HOLD' : station?.faults.length ? `${station.faults.length} fault${station.faults.length > 1 ? 's' : ''}` : 'running'}
        </span>
        <div className="flex-1" />
        <Btn tone="ghost" onClick={() => setDemo(true)}>Demo mode</Btn>
        <button onClick={() => setDrawer(true)} className={`relative px-3 py-2 rounded-xl text-sm font-semibold ${critical ? 'bg-fail/20 text-fail' : 'bg-raised'}`} aria-label={`Alerts, ${open.length} open`}>
          Alerts{open.length > 0 && <span className={`ml-2 num text-xs px-1.5 rounded-full ${critical ? 'bg-fail text-ink' : 'bg-doubt text-ink'}`}>{open.length}</span>}
        </button>
        <select value={role} onChange={e => setRole(e.target.value as Role)} className="bg-raised rounded-xl px-3 py-2 text-sm" aria-label="Acting as">
          {ROLES.map(r => <option key={r} value={r}>as {roleName(r)}</option>)}
        </select>
        <select value={theme} onChange={e => setTheme(e.target.value as any)} className="bg-raised rounded-md px-2 h-8 text-sm border border-line" aria-label="Theme" title="Theme">
          {THEMES.map(t => <option key={t.id} value={t.id}>{t.title}</option>)}
        </select>
        {station?.hold
          ? <Btn tone="pass" onClick={() => hold(false)} disabled={!can(role, 'INSPECTOR', 'QUALITY_MANAGER', 'ADMIN')} title={can(role, 'INSPECTOR', 'QUALITY_MANAGER', 'ADMIN') ? undefined : 'An inspector or above must release a stop'}>Release HOLD</Btn>
          : <button onClick={() => hold(true)} className="px-4 py-2 rounded-xl text-sm font-bold bg-fail text-ink hover:brightness-110 tracking-wide">E-STOP</button>}
      </div>
      {(station?.hold || !!station?.faults.length) && (
        <div role="alert" className="mt-3 rounded-xl px-4 py-2.5 text-sm font-semibold flex flex-wrap gap-2 items-center" style={{ background: 'rgb(var(--fail-rgb) / 0.15)', color: 'var(--fail)' }}>
          {station?.hold
            ? <>Line on HOLD{station.holdReason ? `: ${station.holdReason}` : ''}{station.holdSince ? ` (since ${station.holdSince.slice(11)})` : ''}. Every part is held on the belt; nothing is passed or rejected.</>
            : <>Hardware fault: {station?.faults.join(', ')}. Affected parts are held rather than judged blind. Restore on the Hardware page.</>}
        </div>
      )}
      {drawer && <AlertsDrawer onClose={() => setDrawer(false)} />}
      {demo && <DemoModal onClose={() => setDemo(false)} />}
    </>
  );
}
