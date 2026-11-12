import React, { useEffect, useRef, useState } from 'react';
import { api, Passport as PassportT, Role } from '../api';
import { useStore } from '../store';
import { Btn, Verdict, decisionColor } from '../ui/bits';

/** Fetch now and every `ms`; keeps the last good value while the station is briefly unreachable. */
export function usePoll<T>(fn: () => Promise<T>, ms: number, deps: unknown[] = []): [T | null, () => void, string | null] {
  const [v, setV] = useState<T | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const ref = useRef(fn);
  ref.current = fn;
  const load = () => { ref.current().then(x => { setV(x); setErr(null); }).catch(e => setErr(e.message)); };
  useEffect(() => {
    load();
    if (!ms) return;
    const t = setInterval(load, ms);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return [v, load, err];
}

export const can = (role: Role, ...allowed: Role[]) => allowed.includes(role);
export const roleName = (r: string) => r.replace('_', ' ').toLowerCase();

export function PageHead({ title, sub, aside }: { title: string; sub?: string; aside?: React.ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-3 mb-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {sub && <p className="text-mist mt-1 max-w-3xl">{sub}</p>}
      </div>
      {aside}
    </header>
  );
}

export function Kpi({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: string }) {
  return (
    <div className="panel p-3.5 min-w-0">
      <div className="text-mist text-xs font-medium">{label}</div>
      <div className={`${String(value).length > 7 ? 'text-xl' : 'text-3xl'} font-semibold num mt-1 whitespace-nowrap`} style={tone ? { color: tone } : undefined}>{value}</div>
      {sub && <div className="text-mist text-xs mt-1">{sub}</div>}
    </div>
  );
}

export function SessionPicker({ value, onChange, all = false }: { value: string | null; onChange: (id: string | null) => void; all?: boolean }) {
  const { views } = useStore();
  const list = Object.values(views).filter(v => v.summary);
  return (
    <select value={value ?? ''} onChange={e => onChange(e.target.value || null)} className="bg-raised rounded-lg px-3 py-1.5 text-sm" aria-label="Product line">
      {all && <option value="">All product lines</option>}
      {list.map(v => <option key={v.id} value={v.id}>{(v.summary?.displayName ?? v.summary?.name ?? v.id).replace(/^\d+/, '')} · {v.summary?.plant}</option>)}
    </select>
  );
}

export function Chip({ children, tone = 'var(--mist)' }: { children: React.ReactNode; tone?: string }) {
  return <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold border" style={{ color: tone, borderColor: tone }}>{children}</span>;
}

export const statusTone = (s: string) => /ONLINE|TRACKING|OK|SIMULATED|SENT/.test(s) ? 'var(--pass)' : /QUEUED|THROTTLED/.test(s) ? 'var(--doubt)' : 'var(--fail)';

export function Modal({ onClose, children, title }: { onClose: () => void; children: React.ReactNode; title: string }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 bg-ink/80 backdrop-blur-sm grid place-items-center p-4" onClick={onClose} role="dialog" aria-modal aria-label={title}>
      <div className="bg-surface rounded-2xl p-5 w-full max-w-4xl max-h-[90vh] overflow-auto shadow-2xl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-xl font-semibold">{title}</h2>
          <button onClick={onClose} className="text-mist hover:text-bone text-sm">Close (Esc)</button>
        </div>
        {children}
      </div>
    </div>
  );
}

/** Digital product passport: everything known about one inspected part, with its certificate link. */
export function PassportModal({ rid, onClose }: { rid: string; onClose: () => void }) {
  const [p, setP] = useState<PassportT | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [heat, setHeat] = useState(false);
  useEffect(() => { api.passport(rid).then(setP).catch(e => setErr(e.message)); }, [rid]);
  const r = p?.record;
  return (
    <Modal onClose={onClose} title={`Part passport · ${rid}`}>
      {err && <p className="text-fail">{err}</p>}
      {r && p && (
        <div className="grid md:grid-cols-[320px_1fr] gap-5">
          <div>
            <button onClick={() => setHeat(h => !h)} className="block w-full" aria-label="Toggle heatmap">
              <img src={heat ? r.heat_url : r.image_url} alt="" className="rounded-xl w-full aspect-square object-cover" />
            </button>
            <p className="text-xs text-mist mt-1">{heat ? 'Heatmap' : 'Photo'} · tap to switch</p>
            {!!r.regions?.length && (
              <div className="mt-3 space-y-1.5">
                {r.regions.map(g => (
                  <div key={g.id} className="flex gap-2 items-center text-xs">
                    {g.crop && <img src={g.crop} alt="" className="w-10 h-10 rounded object-cover" />}
                    <span><b>{g.id} {g.label}</b> · {g.severity} · {g.areaPct}% of part</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="space-y-4 text-sm min-w-0">
            <div className="flex items-baseline gap-3 flex-wrap"><Verdict d={r.decision} size="xl" /><span className="text-mist">→ {r.routing ?? '—'}</span></div>
            <p className="voice text-lg leading-snug">{r.explanation}</p>
            <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-2 num">
              {[
                ['Product', `${p.product.replace(/^\d+/, '')} (${p.source})`], ['Plant / station', `${p.plant} · ${p.station}`], ['Inspected', r.created],
                ['Unusualness', r.score.toFixed(4)], ['Pass line', (r.pass_line ?? p.policy.tau_pass).toFixed(4)], ['Fail line', p.policy.tau_fail.toFixed(4)],
                ['p-value vs good', r.p_value], ['Novelty p', r.novelty_p], ['Latency', r.latency_ms ? `${r.latency_ms} ms` : '—'],
                ['Typical AI', r.naive_decision], ['Review', r.review?.final ?? r.review?.status ?? 'none'], ['Truth (dataset)', r.truth === null ? 'unknown' : r.truth ? r.defect_type : 'good'],
              ].map(([k, v]) => <div key={String(k)}><dt className="text-mist text-xs">{k}</dt><dd className="truncate">{String(v)}</dd></div>)}
            </dl>
            {r.quality && <p className="text-xs text-mist">Image check: sharpness {Math.round(r.quality.sharpness * 100)}%, exposure {Math.round(r.quality.exposure * 100)}%, glare {r.quality.glarePct}% (vs references){r.hold_reason ? ` · held: ${r.hold_reason}` : ''}</p>}
            {p.certificate ? (
              <div className="bg-raised rounded-xl p-3">
                <div className="font-semibold">On signed certificate {p.certificate.certificate}</div>
                <div className="text-xs text-mist break-all num">chain hash {p.certificate.hash}</div>
                <a href={p.certificate.verifyUrl} target="_blank" rel="noreferrer" className="text-doubt text-xs">Verify this certificate</a>
              </div>
            ) : <p className="text-xs text-mist">Not yet on a signed certificate (sign one under "Sign the guarantee").</p>}
          </div>
        </div>
      )}
    </Modal>
  );
}

export function DecisionPill({ d }: { d: string }) {
  return <span className="font-semibold text-xs" style={{ color: (decisionColor as any)[d] ?? 'var(--mist)' }}>{d}</span>;
}

export function Confirm({ label, onYes, tone = 'fail', disabled, title }: { label: string; onYes: () => void; tone?: 'fail' | 'doubt' | 'plain'; disabled?: boolean; title?: string }) {
  const [armed, setArmed] = useState(false);
  useEffect(() => { if (!armed) return; const t = setTimeout(() => setArmed(false), 4000); return () => clearTimeout(t); }, [armed]);
  return armed
    ? <Btn tone={tone} onClick={() => { setArmed(false); onYes(); }}>Confirm: {label}</Btn>
    : <Btn tone="ghost" disabled={disabled} title={title} onClick={() => setArmed(true)}>{label}</Btn>;
}
