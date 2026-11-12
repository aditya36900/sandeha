import React, { useEffect, useState } from 'react';
import { api, Role, StationSettings } from '../api';
import { useStore } from '../store';
import { Btn, Panel } from '../ui/bits';
import { Confirm, PageHead, can, roleName, usePoll } from './common';

const LABELS: Record<string, [string, string]> = {
  defaultBudget: ['Default human-review budget', 'share of parts (0.10 = 10%)'],
  falseRejectGuarantee: ['Default false-reject guarantee', 'share of good parts (0.02 = 2%)'],
  costPerEscape: ['Cost of one escaped defect', '₹ (debit note, returns)'],
  costPerFalseReject: ['Cost of one scrapped good part', '₹'],
  costPerReview: ['Cost of one human check', '₹'],
  overloadQueue: ['Review queue alert threshold', 'parts waiting'],
};

const CAN: Record<Role, string[]> = {
  OPERATOR: ['scan parts', 'press emergency HOLD', 'inject faults (rehearsal)', 'ask the AI'],
  INSPECTOR: ['everything an operator can', 'review doubts (one vote)', 'release HOLD', 'restore faults', 'adapt to new conditions'],
  QUALITY_MANAGER: ['everything an inspector can', 'the second, deciding review', 'change guarantees and costs', 'delete product lines', 'reset the station'],
  ADMIN: ['everything', 'station identity', 'reset the station'],
};

export default function Settings() {
  const { role, setRole, setError } = useStore();
  const [s, setS] = useState<StationSettings | null>(null);
  const [draft, setDraft] = useState<Record<string, number>>({});
  const [name, setName] = useState('');
  const [msg, setMsg] = useState<string | null>(null);
  const [audit] = usePoll(() => api.audit(150), 6000);
  useEffect(() => { api.settings().then(x => { setS(x); setDraft(x.settings); setName(x.name); }).catch(e => setError(e.message)); }, [setError]);
  const qm = can(role, 'QUALITY_MANAGER', 'ADMIN');
  const save = async () => {
    try { const x = await api.putSettings({ name, settings: draft }); setS(x); setMsg('Saved and written to the audit log.'); } catch (e: any) { setError(e.message); }
  };
  const reset = async () => { try { await api.reset(true); setMsg('Station reset; demo lines are re-seeding (about a minute).'); } catch (e: any) { setError(e.message); } };
  return (
    <div className="space-y-5">
      <PageHead title="Settings" sub="Station identity, the money behind every decision, who may do what, which AI models run here, and an audit log of every change." />
      <div className="grid xl:grid-cols-2 gap-5">
        <Panel title="Station and costs" aside={!qm ? <span className="text-xs text-mist">read-only for {roleName(role)}</span> : undefined}>
          {s && (
            <div className="space-y-3 text-sm">
              <label className="block">Station name
                <input value={name} disabled={!qm} onChange={e => setName(e.target.value)} className="block w-full bg-raised rounded-lg px-3 py-2 mt-1" /></label>
              <div className="grid sm:grid-cols-2 gap-3">
                {Object.entries(draft).map(([k, v]) => (
                  <label key={k} className="block">{LABELS[k]?.[0] ?? k}
                    <input type="number" step="any" value={v} disabled={!qm} onChange={e => setDraft(d => ({ ...d, [k]: +e.target.value }))}
                      className="block w-full bg-raised rounded-lg px-3 py-2 mt-1 num" />
                    <span className="text-xs text-mist">{LABELS[k]?.[1]}</span>
                  </label>
                ))}
              </div>
              <div className="flex gap-2 items-center"><Btn tone="doubt" disabled={!qm} onClick={save}>Save</Btn>{msg && <span className="text-pass text-xs">{msg}</span>}</div>
            </div>
          )}
        </Panel>
        <Panel title="Roles">
          <ul className="space-y-2 text-sm">
            {(Object.keys(CAN) as Role[]).map(r => (
              <li key={r} className={`rounded-xl p-3 ${r === role ? 'bg-raised ring-1 ring-doubt' : 'bg-raised/50'}`}>
                <div className="flex justify-between items-center">
                  <span className="font-semibold">{roleName(r)} <span className="text-mist font-normal">· {s?.names?.[r]}</span></span>
                  {r === role ? <span className="text-xs text-doubt">you</span> : <button className="text-xs text-doubt" onClick={() => setRole(r)}>switch</button>}
                </div>
                <div className="text-xs text-mist mt-0.5">{CAN[r].join(' · ')}</div>
              </li>
            ))}
          </ul>
          <p className="text-xs text-mist mt-2">The server enforces these: every request carries the role, and forbidden actions are refused, not just hidden.</p>
        </Panel>
      </div>
      <div className="grid xl:grid-cols-2 gap-5">
        <Panel title="AI on this station (all local, nothing leaves the plant)">
          {s && (
            <dl className="text-sm space-y-2">
              {Object.entries(s.models).map(([k, v]) => <div key={k} className="flex justify-between gap-4"><dt className="text-mist capitalize">{k.replace(/([A-Z])/g, ' $1')}</dt><dd className="text-right">{v ?? 'not downloaded'}</dd></div>)}
              <div className="flex justify-between gap-4 border-t border-line pt-2"><dt className="text-mist">Ask Sandeha</dt><dd className="text-right">{s.copilot}</dd></div>
            </dl>
          )}
        </Panel>
        <Panel title="Danger zone">
          <p className="text-sm text-mist mb-3">Deletes every product line and alert, then re-seeds the pcb4 and pcb3 demo lines. Cannot be undone.</p>
          <Confirm label="Reset the station" onYes={reset} disabled={!qm} title={qm ? undefined : 'Quality manager or admin only'} />
        </Panel>
      </div>
      <Panel title="Audit log">
        <div className="overflow-x-auto max-h-96">
          <table className="w-full text-sm num">
            <thead className="text-mist text-xs text-left sticky top-0 bg-surface"><tr><th className="py-1">Time</th><th>Who</th><th>Role</th><th>Action</th><th>Target</th><th>Detail</th></tr></thead>
            <tbody>
              {(audit ?? []).map((a, i) => (
                <tr key={i} className="border-t border-line">
                  <td className="py-1 text-mist text-xs">{a.t}</td><td>{a.who}</td><td className="text-xs">{roleName(a.role)}</td><td>{a.action}</td>
                  <td className="text-xs">{a.target}</td><td className="text-xs text-mist max-w-[360px] truncate" title={JSON.stringify(a.detail)}>{JSON.stringify(a.detail)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!audit?.length && <p className="text-mist text-sm">Nothing logged yet.</p>}
        </div>
      </Panel>
    </div>
  );
}
