import React, { useState } from 'react';
import { api } from '../api';
import { Btn, Panel, reasonText } from '../ui/bits';
import { DecisionPill, PageHead, PassportModal, SessionPicker, usePoll } from './common';

const PAGE = 40;

export default function History() {
  const [decision, setDecision] = useState('');
  const [session, setSession] = useState<string | null>(null);
  const [truth, setTruth] = useState('');
  const [q, setQ] = useState('');
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);
  const [pass, setPass] = useState<string | null>(null);
  const [h] = usePoll(() => api.history({ decision, session: session ?? undefined, truth, q: query, offset, limit: PAGE }), 8000, [decision, session, truth, query, offset]);
  const reset = () => setOffset(0);
  return (
    <div className="space-y-5">
      <PageHead title="History" sub="Every decision ever made on this station. Tap a row for the part's passport: photo, heatmap, numbers, review and certificate."
        aside={<a href={api.historyCsvUrl} className="px-4 py-2 rounded-xl text-sm font-semibold bg-raised hover:bg-line">Download CSV</a>} />
      <Panel>
        <form className="flex flex-wrap gap-2 items-center" onSubmit={e => { e.preventDefault(); setQuery(q); reset(); }}>
          <SessionPicker value={session} onChange={v => { setSession(v); reset(); }} all />
          <select value={decision} onChange={e => { setDecision(e.target.value); reset(); }} className="bg-raised rounded-lg px-3 py-1.5 text-sm" aria-label="Decision">
            <option value="">All decisions</option>{['PASS', 'DOUBT', 'FAIL', 'HOLD'].map(d => <option key={d}>{d}</option>)}
          </select>
          <select value={truth} onChange={e => { setTruth(e.target.value); reset(); }} className="bg-raised rounded-lg px-3 py-1.5 text-sm" aria-label="Truth">
            <option value="">Any truth</option><option value="defect">truly defective</option><option value="good">truly good</option><option value="unknown">unknown (your photos)</option>
          </select>
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search part id, product, defect type, explanation" className="bg-raised rounded-lg px-3 py-1.5 text-sm flex-1 min-w-[220px]" aria-label="Search" />
          <Btn tone="doubt">Search</Btn>
        </form>
      </Panel>
      <Panel aside={<span className="text-mist text-sm num">{h ? `${h.total.toLocaleString()} parts` : ''}</span>} title="Decisions">
        <div className="overflow-x-auto">
          <table className="w-full text-sm num">
            <thead className="text-mist text-xs text-left"><tr><th className="py-1">Part</th><th>Product</th><th>Decision</th><th>Reason</th><th>Unusualness</th><th>Typical AI</th><th>Review</th><th>Truth</th><th>Latency</th><th>Time</th></tr></thead>
            <tbody>
              {(h?.rows ?? []).map(r => {
                const wrong = r.truth !== null && ((r.truth === 1 && r.decision === 'PASS') || (r.truth === 0 && r.decision === 'FAIL'));
                return (
                  <tr key={r.id} className="border-t border-line hover:bg-raised cursor-pointer" onClick={() => setPass(r.id)}>
                    <td className="py-1.5"><span className="flex items-center gap-2"><img src={r.image} alt="" className="w-8 h-8 rounded object-cover" />{r.id}</span></td>
                    <td>{r.product.replace(/^\d+/, '')}</td><td><DecisionPill d={r.decision} /></td>
                    <td className="text-xs text-mist max-w-[200px] truncate">{r.reason ? reasonText[r.reason] ?? r.reason : '—'}</td>
                    <td>{r.score.toFixed(3)}</td><td className="text-xs">{r.naive}</td><td className="text-xs">{r.review ?? '—'}</td>
                    <td className={`text-xs ${wrong ? 'text-fail font-semibold' : ''}`}>{r.truth === null ? '?' : r.truth ? r.defectType : 'good'}{wrong ? ' · wrong' : ''}</td>
                    <td className="text-xs text-mist">{r.latencyMs ? `${Math.round(r.latencyMs)} ms` : '—'}</td><td className="text-xs text-mist">{r.created}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {h && h.total > PAGE && (
          <div className="flex gap-2 items-center mt-3 text-sm">
            <Btn tone="ghost" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Newer</Btn>
            <span className="text-mist num">{offset + 1}–{Math.min(offset + PAGE, h.total)} of {h.total}</span>
            <Btn tone="ghost" disabled={offset + PAGE >= h.total} onClick={() => setOffset(offset + PAGE)}>Older</Btn>
          </div>
        )}
      </Panel>
      {pass && <PassportModal rid={pass} onClose={() => setPass(null)} />}
    </div>
  );
}
