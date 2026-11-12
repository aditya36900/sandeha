import React, { Suspense, lazy, useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { api, InspectionRecord } from '../api';
import { useStore } from '../store';
import { Btn, Dot, Panel, reasonText, rupees, Verdict, Voice, decisionColor } from '../ui/bits';
import DoubtGauge from '../ui/DoubtGauge';
import Conveyor from '../ui/Conveyor';
import DropZone from '../ui/DropZone';
import LiveScan from '../ui/LiveScan';
import FaultLab from '../ui/FaultLab';
import { BoardMapT } from '../api';

const Twin3D = lazy(() => import('../ui/Twin3D'));
const COST = { escape: 2500, falseReject: 150, review: 4 };

function Arena({ records }: { records: InspectionRecord[] }) {
  const known = records.filter(r => r.truth !== null && !r.ghost);
  const calc = (pick: (r: InspectionRecord) => string) => {
    const escapes = known.filter(r => r.truth === 1 && pick(r) === 'PASS').length;
    const falseRejects = known.filter(r => r.truth === 0 && pick(r) === 'FAIL').length;
    const reviewed = known.filter(r => pick(r) === 'DOUBT').length;
    return { escapes, falseRejects, reviewed, cost: escapes * COST.escape + falseRejects * COST.falseReject + reviewed * COST.review };
  };
  const ours = calc(r => r.decision);
  const naive = calc(r => r.naive_decision);
  const defects = known.filter(r => r.truth === 1).length;
  const Row = ({ label, a, b, money }: { label: string; a: number; b: number; money?: boolean }) => (
    <tr className="border-t border-line">
      <td className="py-2 text-mist">{label}</td>
      <td className="py-2 text-right num font-semibold">{money ? rupees(b) : b}</td>
      <td className="py-2 text-right num font-semibold text-doubt">{money ? rupees(a) : a}</td>
    </tr>
  );
  return (
    <Panel title="Same parts, two inspectors" aside={<span className="text-mist text-sm num">{known.length} parts · {defects} truly defective</span>}>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-mist"><th className="text-left font-normal" /><th className="text-right font-normal">Typical AI</th><th className="text-right font-normal">Sandeha</th></tr>
        </thead>
        <tbody>
          <Row label="Defects shipped to customer" a={ours.escapes} b={naive.escapes} />
          <Row label="Good parts scrapped" a={ours.falseRejects} b={naive.falseRejects} />
          <Row label="Asked a person" a={ours.reviewed} b={naive.reviewed} />
          <Row label="Cost of mistakes" a={ours.cost} b={naive.cost} money />
        </tbody>
      </table>
      <p className="text-mist text-xs mt-2">Costs assume ₹2,500 per escaped defect (debit note), ₹150 per scrapped good part, ₹4 per human check. The typical AI uses one threshold and never asks.</p>
    </Panel>
  );
}

function ReviewQueue({ records }: { records: InspectionRecord[] }) {
  const { sessionId, role, setRole, reviewer, setError, setSelectedRecord } = useStore();
  const { view } = useStore();
  const pending = records.filter(r => r.decision === 'DOUBT' && !['GOOD', 'DEFECT', 'GHOST_CHECKED'].includes(r.review.final ?? ''));
  const [order, setOrder] = useState<{ id: string; teachValue: number; why: string }[]>([]);
  const pendingKey = pending.map(r => r.id + (r.review.votes?.length ?? 0)).join(',');
  useEffect(() => {
    if (!sessionId) return;
    api.queue(sessionId).then(setOrder).catch(() => setOrder([]));
  }, [sessionId, pendingKey]);
  const byId = new Map(pending.map(r => [r.id, r] as const));
  const ordered = order.map(o => ({ o, r: byId.get(o.id) })).filter(x => x.r) as { o: { id: string; teachValue: number; why: string }; r: InspectionRecord }[];
  const queue = (ordered.length ? ordered : pending.slice(-6).reverse().map(r => ({ o: { id: r.id, teachValue: 0, why: '' }, r }))).slice(0, 6);
  const reviewers = Object.entries(view?.summary?.reviewers ?? {});
  const act = async (r: InspectionRecord, v: 'GOOD' | 'DEFECT') => {
    try {
      await api.review(sessionId!, r.id, v, reviewer, role);
    } catch (e: any) {
      setError(e.message);
    }
  };
  return (
    <Panel title="Waiting for a person" aside={
      <select value={role} onChange={e => setRole(e.target.value as any)} className="bg-raised rounded-lg px-2 py-1 text-sm" aria-label="Reviewer">
        <option value="OPERATOR">Line operator (cannot review)</option>
        <option value="INSPECTOR">Rajesh K. · inspector</option>
        <option value="QUALITY_MANAGER">Sunita M. · quality manager</option>
        <option value="ADMIN">Station admin</option>
      </select>}>
      {queue.length === 0 && <p className="text-mist text-sm">Nothing to review. Parts I'm unsure about will land here.</p>}
      <ul className="space-y-3">
        {queue.map(({ o, r }, i) => (
          <li key={r.id} className={`flex gap-3 items-center ${i === 0 && o.why ? 'bg-raised rounded-xl p-2 -mx-2' : ''}`}>
            <button onClick={() => setSelectedRecord(r.id)} className="shrink-0">
              <img src={r.heat_url} alt="" className="w-16 h-16 rounded-lg object-cover" />
            </button>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-doubt">{reasonText[r.doubt_reason ?? ''] ?? 'Unsure'}</div>
              {i === 0 && o.why && <div className="text-xs text-pass">Answer this first: it teaches me most ({o.why})</div>}
              <div className="text-xs text-mist truncate">{r.review.status ?? r.id}</div>
              <div className="flex gap-2 mt-1.5">
                <Btn tone="ghost" onClick={() => act(r, 'GOOD')}>Good</Btn>
                <Btn tone="ghost" onClick={() => act(r, 'DEFECT')}>Defect</Btn>
              </div>
            </div>
          </li>
        ))}
      </ul>
      <p className="text-mist text-xs mt-3">I only learn from a part after two different people agree, and I order the queue by how much each answer would teach me. Some items are known-answer checks that measure reviewer reliability.</p>
      {reviewers.length > 0 && (
        <div className="mt-3 border-t border-line pt-3">
          <div className="text-xs text-mist mb-1">Reviewer reliability (known-answer checks)</div>
          {reviewers.map(([name, r]) => (
            <div key={name} className="flex justify-between text-sm num">
              <span>{name}</span>
              <span className={r.ghosts && r.ghostCorrect / r.ghosts < 0.8 ? 'text-fail' : 'text-mist'}>
                {r.ghosts ? `${r.ghostCorrect}/${r.ghosts} correct` : 'no checks yet'} · {r.reviews} reviews
              </span>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

export default function Line() {
  const { view, sessionId, setError, selectedRecord, setSelectedRecord } = useStore();
  const [own, setOwn] = useState<File[]>([]);
  const [heat3d, setHeat3d] = useState<{ id: string; heat: number[] } | null>(null);
  const [extra, setExtra] = useState<Record<string, InspectionRecord>>({});
  const [board, setBoard] = useState<BoardMapT | null>(null);
  const records = view?.records ?? [];
  const nRec = records.length;
  // the component map: built in the background after learning; refreshed as parts are checked
  useEffect(() => {
    if (!sessionId) return;
    let live = true;
    let t: ReturnType<typeof setTimeout> | undefined;
    const load = () => api.board(sessionId).then(b => {
      if (!live) return;
      setBoard(b);
      if (b.status === 'building') t = setTimeout(load, 5000);
    }).catch(() => {});
    load();
    return () => { live = false; if (t) clearTimeout(t); };
  }, [sessionId, Math.floor(nRec / 5)]);
  const pick = (id?: string | null) => (id ? records.find(r => r.id === id) ?? extra[id] : undefined);
  const current = pick(selectedRecord) ?? records[records.length - 1];
  const curId = current?.id;
  const curHas = current?.has_twin_heat;
  useEffect(() => {
    if (!sessionId || !curId || !curHas || heat3d?.id === curId) return;
    let live = true;
    api.heat(sessionId, curId).then(h => { if (live && h.heat) setHeat3d({ id: curId, heat: h.heat }); }).catch(() => {});
    return () => { live = false; };
  }, [sessionId, curId, curHas]);
  if (!view || !sessionId) return null;
  const isUpload = view.summary?.source === 'Upload';
  const inspectOwn = async () => {
    try { await api.inspectBatch(sessionId, own); setOwn([]); setSelectedRecord(null); } catch (e: any) { setError(e.message); }
  };
  // the record from the scan call carries the named regions; prefer it over the event copy if that one is older
  const shown = current && extra[current.id] ? { ...current, ...extra[current.id] } : current;

  return (
    <div className="grid grid-cols-1 2xl:grid-cols-[minmax(0,1fr)_420px] gap-5">
      <div className="space-y-5 min-w-0">
        {view.alarm && <div className="text-doubt text-sm font-semibold">Conditions changed: auto-pass suspended</div>}
        <LiveScan sessionId={sessionId} records={records} policy={view.policy} cloud={view.cloud} patches={null}
          memories={view.patches ?? null} heat3d={heat3d && heat3d.id === shown?.id ? heat3d.heat : null} selected={shown} isUpload={isUpload}
          onShow={rid => setSelectedRecord(rid)} onRecord={r => setExtra(x => ({ ...x, [r.id]: r }))} board={board} />

        {board?.status === 'ready' && (
          <FaultLab sessionId={sessionId} board={board} onRecord={r => { setExtra(x => ({ ...x, [r.id]: r })); setSelectedRecord(r.id); window.scrollTo({ top: 0, behavior: 'smooth' }); }} />
        )}
        {board?.status === 'building' && <p className="text-sm text-mist">Mapping every component on the golden board and calibrating each one on separate good boards (about a minute)…</p>}

        <div>
          <h3 className="text-sm font-semibold mb-2">Everything scanned so far (tap one to look again)</h3>
          <Conveyor records={records} selected={current?.id} onSelect={setSelectedRecord} />
        </div>

        <details className="bg-surface rounded-2xl px-5 py-3" open={isUpload && records.length === 0}>
          <summary className="cursor-pointer text-sm font-semibold">Scan your own photos</summary>
          <div className="mt-3 grid md:grid-cols-[1fr_auto] gap-3 items-end">
            <DropZone label="Photos to scan" hint="Same product, camera and framing as the reference photos. Each one goes down the line." files={own} onFiles={setOwn} accent="var(--doubt)" />
            <Btn tone="doubt" disabled={!own.length} onClick={inspectOwn}>Scan {own.length || ''} photo{own.length === 1 ? '' : 's'}</Btn>
          </div>
        </details>

        {shown && (
          <Panel title="Why I think so">
            <div className="grid md:grid-cols-[1fr_1fr] gap-5">
              <div>
                <h3 className="text-sm font-semibold mb-2">Closest cases I compared it with</h3>
                <div className="flex gap-3">
                  {shown.precedents.map((p, i) => (
                    <figure key={i} className="w-28">
                      <img src={p.thumb ?? p.image} alt="" className="rounded-lg w-28 h-28 object-cover" />
                      <figcaption className="text-xs text-mist mt-1">{p.label} · {Math.round(p.similarity * 100)}% alike</figcaption>
                    </figure>
                  ))}
                </div>
              </div>
              {shown.counterfactual && (
                <div>
                  <h3 className="text-sm font-semibold mb-2">What it should look like</h3>
                  <div className="flex gap-3 items-center">
                    <figure className="w-28"><img src={shown.counterfactual.query} alt="" className="rounded-lg" /><figcaption className="text-xs text-mist mt-1">This part</figcaption></figure>
                    <figure className="w-28"><img src={shown.counterfactual.reference} alt="" className="rounded-lg" /><figcaption className="text-xs text-mist mt-1">Verified good</figcaption></figure>
                  </div>
                </div>
              )}
            </div>
            <div className="text-sm mt-4 text-mist">A typical single-threshold AI would have said <span className="font-semibold" style={{ color: decisionColor[shown.naive_decision] }}>{shown.naive_decision === 'PASS' ? 'pass' : 'fail'}</span>.
              {shown.hive_match && <span className="text-pass"> Recognised from {shown.hive_match.from}: {shown.hive_match.label}.</span>}</div>
          </Panel>
        )}
      </div>

      <div className="space-y-5">
        <Arena records={records} />
        <ReviewQueue records={records} />
        <Panel title="Every decision so far">
          <div className="flex gap-4 text-sm flex-wrap">
            {(['PASS', 'DOUBT', 'FAIL', 'HOLD'] as const).map(d => (
              <span key={d} className="flex items-center gap-1.5"><Dot d={d} /><span className="num">{records.filter(r => r.decision === d).length}</span> <Verdict d={d} size="sm" /></span>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}
