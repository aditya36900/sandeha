import React, { Suspense, lazy, useEffect, useState } from 'react';
import { api } from '../api';
import { useStore } from '../store';
import { Btn, Panel, Verdict, Voice, decisionColor, pct, rupees } from '../ui/bits';
import DoubtGauge from '../ui/DoubtGauge';
import { STATUS_COLOR } from '../ui/Board3D';
import { PageHead } from '../room/common';
import { LinePicker, prettyStatus, useBoardMap, useSid } from './common';

const Board3D = lazy(() => import('../ui/Board3D'));
const VERDICT_TONE: Record<string, string> = { defect: 'var(--fail)', 'process indicator': 'var(--doubt)', 'defect if functional damage': 'var(--doubt)' };

function Dossier({ sid, rid, onDecided }: { sid: string; rid: string; onDecided: () => void }) {
  const { reviewer, role, setError, views, notify } = useStore();
  const board = useBoardMap(sid);
  const [d, setD] = useState<any | null>(null);
  const [v, setV] = useState<any | null>(null);
  const [vBusy, setVBusy] = useState(false);
  const [heat, setHeat] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [heat3d, setHeat3d] = useState<number[] | null>(null);
  const [chips, setChips] = useState<any | null>(null);
  const [cBusy, setCBusy] = useState(false);
  const cloud = views[sid]?.cloud ?? null;
  useEffect(() => {
    setD(null); setV(null); setMsg(null); setHeat3d(null); setChips(null);
    api.dossier(sid, rid).then(setD).catch(e => setError(e.message));
    api.heat(sid, rid).then(h => setHeat3d(h.heat)).catch(() => {});
  }, [sid, rid, setError]);
  if (!d) return <Panel><p className="text-mist">Building the dossier…</p></Panel>;
  const r = d.record;
  const sys = d.system;
  const comps = (d.components?.faults ?? []) as any[];
  const decide = async (verdict: 'GOOD' | 'DEFECT') => {
    try {
      const out = await api.review(sid, rid, verdict, reviewer, role);
      setMsg(out.status);
      notify(`${verdict === 'GOOD' ? 'Approved' : 'Rejected'} by ${reviewer}: ${out.status}${verdict === 'DEFECT' ? ' A repair ticket is waiting on the Rework step.' : ''}`, verdict === 'GOOD' ? 'pass' : 'fail');
      api.dossier(sid, rid).then(setD).catch(() => {});
      onDecided();
    } catch (e: any) { setError(e.message); }
  };
  const askVlm = async () => {
    setVBusy(true);
    try { setV(await api.dossierVlm(sid, rid)); } catch (e: any) { setError(e.message); } finally { setVBusy(false); }
  };
  const votes = (r.review?.votes ?? []) as { by: string; verdict: string }[];
  return (
    <div className="space-y-4">
      <Panel>
        <div className="flex flex-wrap items-baseline gap-4 justify-between">
          <div className="flex items-baseline gap-4"><Verdict d={r.decision} size="xl" /><span className="text-mist num">{r.id} · {r.created}</span></div>
          <div className="flex gap-2 items-center flex-wrap">
            <span className="text-xs text-mist">IPC-A-610 {d.ipcClasses?.[d.ipcClass]}</span>
            {r.synthetic && <span className="text-xs text-doubt">fault-lab board: {r.synthetic}</span>}
          </div>
        </div>
        <Voice className="mt-2">{sys.explanation}</Voice>
        <div className="grid lg:grid-cols-[minmax(0,380px)_1fr] gap-5 mt-4">
          <div>
            <button onClick={() => setHeat(h => !h)} className="block w-full" aria-label="Toggle heatmap">
              <img src={heat ? r.heat_url : r.image_url} alt="Board" className="rounded-xl w-full aspect-square object-cover" />
            </button>
            <p className="text-xs text-mist mt-1">{heat ? 'Where it looks unusual' : 'The board as photographed'} · tap to switch</p>
          </div>
          <div className="space-y-4 min-w-0">
            <DoubtGauge score={sys.score} tauPass={sys.passLine} tauFail={sys.failLine} decision={r.decision} />
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm num">
              <div><div className="text-mist text-xs">Unusualness</div><div className="text-xl">{sys.score.toFixed(3)}</div></div>
              <div><div className="text-mist text-xs">Good boards this unusual</div><div className="text-xl">{pct(sys.goodAsUnusual)}</div></div>
              <div><div className="text-mist text-xs">Real defects less unusual</div><div className="text-xl">{sys.defectsLessUnusual == null ? '—' : pct(sys.defectsLessUnusual, 0)}</div></div>
              <div><div className="text-mist text-xs">How unsure</div><div className="text-xl">{Math.round(sys.uncertainty * 100)}%</div></div>
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-xl bg-raised p-3"><div className="text-mist text-xs">If you pass it (expected cost)</div><div className="text-xl num">{rupees(d.risk.passIt)}</div></div>
              <div className="rounded-xl bg-raised p-3"><div className="text-mist text-xs">If you reject it (expected cost)</div><div className="text-xl num">{rupees(d.risk.rejectIt)}</div></div>
            </div>
            <p className="text-[11px] text-mist">{d.risk.note}. A typical single-threshold AI would say {sys.naive}. Good boards are wrongly rejected at most {pct(sys.falseRejectGuarantee, 0)} of the time.</p>
          </div>
        </div>
      </Panel>

      <Panel title="Critical analysis: both sides, from the measurements" aside={<span className="text-xs text-mist">evidence leans: <b>{d.critical.balance}</b></span>}>
        <div className="grid md:grid-cols-2 gap-4">
          <div className="rounded-xl p-3" style={{ background: 'rgb(var(--fail-rgb) / 0.08)' }}>
            <div className="font-semibold text-fail mb-2">The case that it is defective</div>
            {d.critical.caseForFail.length ? <ul className="space-y-1.5 text-sm list-disc pl-4">{d.critical.caseForFail.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul> : <p className="text-mist text-sm">No evidence for a defect.</p>}
          </div>
          <div className="rounded-xl p-3" style={{ background: 'rgb(var(--pass-rgb) / 0.08)' }}>
            <div className="font-semibold text-pass mb-2">The case that it is fine</div>
            {d.critical.caseForPass.length ? <ul className="space-y-1.5 text-sm list-disc pl-4">{d.critical.caseForPass.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul> : <p className="text-mist text-sm">No evidence that it is fine.</p>}
          </div>
        </div>
        {!!d.critical.whatWouldChangeIt.length && (
          <div className="mt-3 text-sm"><span className="font-semibold">What would change the decision: </span>{d.critical.whatWouldChangeIt.join(' ')}</div>
        )}
      </Panel>

      {cloud && board?.status === 'ready' && board.components && (
        <Panel title={r.board?.aligned ? "This board in 3D: its own photo on the relief, faults boxed" : "The board in 3D (component models; this older scan has no photo of its own)"}>
          <Suspense fallback={<div className="h-[440px] rounded-xl bg-raised" />}>
            <Board3D cloud={cloud} components={board.components} faults={comps.filter(f => f.level === 'fault')} watch={comps.filter(f => f.level === 'watch')} regions={d.regions} heat={heat3d} height={460} verdict={r.decision}
              photo={r.board?.aligned ?? null} key={r.id} />
          </Suspense>
        </Panel>
      )}

      <Panel title={`Components: ${d.components?.checked ?? '—'} checked, ${comps.length} flagged`}>
        {comps.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-mist text-xs text-left"><tr><th className="py-1">Part</th><th>Problem</th><th>IPC-A-610</th><th>Likely started at</th><th>Check there</th><th>Repair</th></tr></thead>
              <tbody>
                {comps.map((f: any) => (
                  <tr key={f.id} className={`border-t border-line align-top ${f.level === 'watch' ? 'opacity-70' : ''}`}>
                    <td className="py-2 pr-3 whitespace-nowrap"><b style={{ color: STATUS_COLOR[f.status] }}>{f.id}</b> <span className="text-mist">{f.kind}</span>{f.level === 'watch' && <div className="text-[10px] text-mist">watch only</div>}</td>
                    <td className="pr-3"><b>{prettyStatus(f.status)}</b><div className="text-xs text-mist">{f.why?.[0]}</div></td>
                    <td className="pr-3"><b style={{ color: VERDICT_TONE[f.ipc.verdict] ?? 'var(--mist)' }}>{f.ipc.verdict}</b><div className="text-xs text-mist">{f.ipc.rule}</div></td>
                    <td className="pr-3">{f.origin}<div className="text-xs text-mist">{f.cause}</div></td>
                    <td className="pr-3 text-xs">{f.check}</td>
                    <td className="text-xs">{f.action}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="text-mist text-sm">Every component matches the good boards.</p>}
      </Panel>

      <Panel title="What the local vision-language model sees" aside={<Btn tone="ghost" disabled={vBusy} onClick={askVlm}>{vBusy ? 'Looking (10-30 s)…' : v ? 'Look again' : 'Ask it'}</Btn>}>
        {!v && <p className="text-mist text-sm">Qwen2-VL-2B runs on this station. It looks at each flagged close-up and the whole board, and says whether it agrees with the system. It is advisory only.</p>}
        {v && !v.available && <p className="text-mist text-sm">The local model is not downloaded on this station.</p>}
        {v?.available && (
          <div className="space-y-3 text-sm">
            {v.overall && <Voice>{v.overall}</Voice>}
            {v.items.map((i: any) => (
              <div key={i.region} className="rounded-xl bg-raised p-3">
                <div className="flex justify-between gap-3"><b>{i.region}</b><span style={{ color: i.agrees === true ? 'var(--pass)' : i.agrees === false ? 'var(--fail)' : 'var(--mist)' }}>{i.agrees === true ? 'agrees' : i.agrees === false ? 'disagrees' : 'no clear answer'}</span></div>
                <div className="text-xs text-mist">system says: {i.claim}</div>
                <div className="mt-1">{i.seen}</div>
              </div>
            ))}
            <p className="text-xs text-mist">{v.agreement} · {v.caveat}</p>
          </div>
        )}
      </Panel>

      <Panel title="Chip identity" aside={<Btn tone="ghost" disabled={cBusy} onClick={async () => { setCBusy(true); try { setChips(await api.chips(sid, rid)); } catch (e: any) { setError(e.message); } finally { setCBusy(false); } }}>{cBusy ? 'Reading markings…' : chips ? 'Read again' : 'Read chip markings'}</Btn>}>
        {!chips && <p className="text-mist text-sm">Reads the part number printed on each IC and compares it with the golden board: catches wrong, re-marked, counterfeit or burnt chips.</p>}
        {chips?.available && (
          <ul className="space-y-1 text-sm">
            {chips.chips.map((c: any) => (
              <li key={c.id}><b>{c.id}</b> expected <span className="font-mono">{c.expected || '—'}</span>, reads <span className="font-mono">{c.read || '—'}</span> ·{' '}
                <b style={{ color: c.verdict === 'MATCH' ? 'var(--pass)' : c.verdict === 'PARTIAL' ? 'var(--doubt)' : 'var(--fail)' }}>{c.verdict.toLowerCase()}</b> ({Math.round(c.similarity * 100)}%)</li>
            ))}
          </ul>
        )}
      </Panel>

      <div className="grid md:grid-cols-2 gap-4">
        <Panel title="Closest past boards">
          <div className="flex gap-3 flex-wrap">
            {(d.precedents ?? []).map((p: any, i: number) => (
              <figure key={i} className="w-28"><img src={p.thumb ?? p.image} alt="" className="rounded-lg w-28 h-28 object-cover" /><figcaption className="text-xs text-mist mt-1">{p.label} · {Math.round(p.similarity * 100)}% alike</figcaption></figure>
            ))}
          </div>
        </Panel>
        {d.counterfactual && (
          <Panel title="What it should look like">
            <div className="flex gap-3"><figure className="w-32"><img src={d.counterfactual.query} alt="" className="rounded-lg" /><figcaption className="text-xs text-mist">this board</figcaption></figure>
              <figure className="w-32"><img src={d.counterfactual.reference} alt="" className="rounded-lg" /><figcaption className="text-xs text-mist">verified good</figcaption></figure></div>
          </Panel>
        )}
      </div>

      <Panel title="Your decision">
        <p className="text-sm text-mist mb-3">You are signing as <b className="text-bone">{reviewer}</b>. Two different people must agree before the line learns from this board; a disagreement goes to the quality manager.</p>
        {votes.length > 0 && <p className="text-sm mb-2">Votes so far: {votes.map(x => `${x.by}: ${x.verdict}`).join(' · ')}</p>}
        <div className="flex gap-2 flex-wrap">
          <Btn tone="pass" onClick={() => decide('GOOD')}>Approve: the board is good</Btn>
          <Btn tone="fail" onClick={() => decide('DEFECT')}>Reject: send to rework</Btn>
        </div>
        {msg && <p className="text-sm mt-2">{msg}</p>}
      </Panel>
    </div>
  );
}

export default function Approval() {
  const [sid, setSid] = useSid();
  const { selectedRecord } = useStore();
  const [q, setQ] = useState<any[]>([]);
  const [rid, setRid] = useState<string | null>(selectedRecord ?? new URLSearchParams(window.location.search).get('part'));  // a board picked on another step (or linked) opens straight away
  const load = () => { if (sid) api.approvalQueue(sid).then(x => { setQ(x); setRid(r => r ?? x[0]?.part ?? null); }).catch(() => {}); };
  useEffect(load, [sid]);
  return (
    <div className="space-y-5">
      <PageHead title="Approval desk" sub="For the person signing a board off at the bench: the system's verdict and evidence, a critical case for and against, every component graded against IPC-A-610 with its likely cause and repair, what the local AI sees, and the cost either way."
        aside={<LinePicker sid={sid} setSid={s => { setSid(s); setRid(null); }} />} />
      <div className="grid xl:grid-cols-[300px_minmax(0,1fr)] gap-5 items-start">
        <Panel title={`Waiting for a person (${q.length})`}>
          {!q.length && <p className="text-mist text-sm">Nothing waiting. Doubts, rejects and boards with watch flags land here.</p>}
          <ul className="space-y-2 max-h-[75vh] overflow-auto pr-1">
            {q.map(x => (
              <li key={x.part}>
                <button onClick={() => setRid(x.part)} className={`w-full flex gap-2 items-center text-left rounded-xl p-2 ${rid === x.part ? 'bg-raised ring-1 ring-doubt' : 'hover:bg-raised'}`}>
                  <img src={x.image} alt="" className="w-12 h-12 rounded-lg object-cover" />
                  <div className="min-w-0 text-xs">
                    <div className="font-semibold text-sm" style={{ color: decisionColor[x.decision as 'PASS'] }}>{x.decision} <span className="text-mist font-normal num">{x.part.split('-').pop()}</span></div>
                    <div className="text-mist truncate">{x.why}</div>
                    <div className="text-mist">{x.faults} component fault{x.faults === 1 ? '' : 's'} · {x.votes} vote{x.votes === 1 ? '' : 's'}{x.synthetic ? ' · fault lab' : ''}</div>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </Panel>
        {sid && rid ? <Dossier sid={sid} rid={rid} onDecided={load} /> : <Panel><p className="text-mist">Pick a board on the left.</p></Panel>}
      </div>
    </div>
  );
}
