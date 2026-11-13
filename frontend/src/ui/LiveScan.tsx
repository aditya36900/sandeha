import React, { Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { api, BoardMapT, Cloud, DefectRegion, InspectionRecord, LotPart, Policy } from '../api';
import { ComponentCheck } from './BoardViews';
import CameraScan from './CameraScan';
import UploadScan from './UploadScan';
import Comparator from './Comparator';
import Detectors from './Detectors';
import { Btn, Panel, Verdict, Voice, decisionColor, reasonText } from './bits';
import { useStore } from '../store';
import DoubtGauge from './DoubtGauge';

const Twin3D = lazy(() => import('./Twin3D'));
const Board3D = lazy(() => import('./Board3D'));
const SEV: Record<DefectRegion['severity'], string> = { minor: 'var(--doubt)', major: 'var(--fail)', critical: '#ff3b6b' };

type Phase = 'idle' | 'see' | 'understand' | 'compare' | 'locate' | 'decide' | 'done';
const PHASES: { key: Exclude<Phase, 'idle' | 'done'>; title: string }[] = [
  { key: 'see', title: 'Capture + image check' },
  { key: 'understand', title: 'Read the part, patch by patch' },
  { key: 'compare', title: 'Compare with every good part I know' },
  { key: 'locate', title: 'Locate and name what is wrong' },
  { key: 'decide', title: 'Doubt, then decide' },
];

function stageMs(r: InspectionRecord, k: string) {
  const s = r.stage_ms || {};
  if (k === 'see') return s.see;
  if (k === 'understand' || k === 'compare') return s['understand+compare'] != null ? s['understand+compare'] / 2 : undefined;
  if (k === 'locate') return s.regions;
  if (k === 'decide') return (s['doubt+decide'] ?? 0) + (s.explain ?? 0);
}

function stageDetail(r: InspectionRecord, k: string, patches: number | null, memories: number | null) {
  const q = r.quality;
  if (k === 'see') {
    if (r.hold_reason) return r.hold_reason;
    return q ? `sharpness ${Math.round(q.sharpness * 100)}% · exposure ${Math.round(q.exposure * 100)}% · glare ${q.glarePct}% of reference` : 'image accepted';
  }
  if (k === 'understand') return `${(patches ?? 1024).toLocaleString()} patches → DINOv2 features (frozen, never trained on this part)`;
  if (k === 'compare') return `each patch vs its nearest of ${memories ? memories.toLocaleString() : 'all'} good-patch memories · most unusual spot ${(r.hotspot.value).toFixed(3)}`;
  if (k === 'locate') {
    const n = r.regions?.length ?? 0;
    if (r.decision === 'PASS' || r.decision === 'HOLD') return 'nothing to locate';
    return n ? `${n} region${n > 1 ? 's' : ''}: ${r.regions!.map(g => g.label).join(', ')}` : 'unusual overall, no single spot stands out';
  }
  return r.doubt_reason ? reasonText[r.doubt_reason] : `unusualness ${r.score.toFixed(3)} vs calibrated lines`;
}

/** The photo under the scanner: sweep, patch grid, heat reveal, defect boxes with leader lines. */
function Scanner({ rec, phase, active, setActive }: { rec: InspectionRecord; phase: Phase; active: string | null; setActive: (id: string | null) => void }) {
  const at = (p: Phase) => PHASES.findIndex(x => x.key === p);
  const reached = (p: Phase) => phase === 'done' || (phase !== 'idle' && at(phase as any) >= at(p));
  const regions = rec.regions || [];
  return (
    <div className="relative w-full aspect-square rounded-xl overflow-hidden bg-ink select-none">
      <img src={rec.image_url} alt="Part under the scanner" className="absolute inset-0 w-full h-full object-cover" />
      {/* patch grid: what the backbone actually sees */}
      <div className={`absolute inset-0 transition-opacity duration-500 ${phase === 'understand' ? 'opacity-60' : 'opacity-0'}`}
        style={{ backgroundImage: 'linear-gradient(rgba(236,231,218,.35) 1px, transparent 1px), linear-gradient(90deg, rgba(236,231,218,.35) 1px, transparent 1px)', backgroundSize: '3.125% 3.125%' }} />
      {/* heat reveal, top to bottom, while comparing */}
      <img src={rec.heat_url} alt="" aria-hidden
        className="absolute inset-0 w-full h-full object-cover"
        style={{ clipPath: reached('compare') ? 'inset(0 0 0 0)' : 'inset(0 0 100% 0)', transition: phase === 'compare' ? 'clip-path 900ms linear' : 'none', opacity: reached('locate') ? 0.55 : 1 }} />
      {/* sweep line */}
      {(phase === 'see' || phase === 'compare') && (
        <motion.div key={phase} className="absolute left-0 right-0 h-[3px] bg-doubt shadow-[0_0_18px_4px_rgba(242,169,59,.55)]"
          initial={{ top: '0%' }} animate={{ top: '100%' }} transition={{ duration: phase === 'see' ? 0.6 : 0.9, ease: 'linear' }} />
      )}
      {/* defect boxes + leader lines to their labels */}
      {reached('locate') && regions.length > 0 && (
        <svg className="absolute inset-0 w-full h-full" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
          {regions.map((g, i) => {
            const [x, y, w, h] = g.bbox.map(v => v * 100);
            const left = g.centroid[0] < 0.5;
            const lx = left ? Math.min(96, x + w + 6) : Math.max(4, x - 6);
            const ly = Math.max(6, Math.min(94, y - 4 + i * 2));
            const c = SEV[g.severity];
            return (
              <g key={g.id} opacity={active && active !== g.id ? 0.35 : 1}>
                <motion.rect x={x - 1} y={y - 1} width={w + 2} height={h + 2} fill="none" stroke={c} strokeWidth={0.6} rx={1}
                  initial={{ opacity: 0, scale: 1.6 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: i * 0.18 }} style={{ transformOrigin: `${x + w / 2}px ${y + h / 2}px` }} />
                <motion.line x1={x + w / 2} y1={y + h / 2} x2={lx} y2={ly} stroke={c} strokeWidth={0.35}
                  initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ delay: 0.15 + i * 0.18, duration: 0.3 }} />
              </g>
            );
          })}
        </svg>
      )}
      {reached('locate') && regions.map((g, i) => {
        const [x, y, w] = g.bbox;
        const left = g.centroid[0] < 0.5;
        const lx = left ? Math.min(0.96, x + w + 0.06) : Math.max(0.04, x - 0.06);
        const ly = Math.max(0.06, Math.min(0.94, y - 0.04 + i * 0.02));
        return (
          <motion.button key={g.id} onMouseEnter={() => setActive(g.id)} onMouseLeave={() => setActive(null)} onClick={() => setActive(active === g.id ? null : g.id)}
            initial={{ opacity: 0, y: 6 }} animate={{ opacity: active && active !== g.id ? 0.45 : 1, y: 0 }} transition={{ delay: 0.3 + i * 0.18 }}
            className="absolute text-[11px] leading-tight rounded-md px-2 py-1 bg-ink/90 border whitespace-nowrap"
            style={{ left: `${lx * 100}%`, top: `${ly * 100}%`, transform: `translate(${left ? '0' : '-100%'}, -50%)`, borderColor: SEV[g.severity] }}>
            <span className="font-semibold" style={{ color: SEV[g.severity] }}>{g.id} {g.label}</span>
            <span className="text-mist"> · {g.severity}</span>
          </motion.button>
        );
      })}
      {/* verdict stamp */}
      <AnimatePresence>
        {reached('decide') && (
          <motion.div initial={{ opacity: 0, scale: 1.8, rotate: -8 }} animate={{ opacity: 1, scale: 1, rotate: -8 }} transition={{ type: 'spring', stiffness: 260, damping: 18 }}
            className="absolute right-3 bottom-3 px-3 py-1 rounded-lg border-2 text-2xl font-semibold uppercase tracking-wider bg-ink/70"
            style={{ color: decisionColor[rec.decision], borderColor: decisionColor[rec.decision] }}>{rec.decision}</motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Tray({ lot, scanned, reveal, busyToken, onScan, onOpen }: {
  lot: LotPart[]; scanned: Record<string, InspectionRecord>; reveal: boolean; busyToken: string | null; onScan: (t: string) => void; onOpen: (rid: string) => void;
}) {
  return (
    <div className="grid grid-cols-6 sm:grid-cols-8 xl:grid-cols-12 gap-2">
      {lot.map(p => {
        const r = scanned[p.token];
        const truthBad = r?.truth === 1;
        return (
          <button key={p.token} disabled={!r && !!busyToken} onClick={() => (r ? onOpen(r.id) : onScan(p.token))}
            className={`relative rounded-lg overflow-hidden aspect-square border-2 transition ${busyToken === p.token ? 'border-doubt animate-pulse' : r ? 'border-transparent' : 'border-line hover:border-bone'}`}
            title={r ? `${r.id}: ${r.decision} - click to look again` : 'Unlabelled part - click to scan'}>
            <img src={p.thumb} alt="Unlabelled part" className={`w-full h-full object-cover ${r ? 'opacity-50 hover:opacity-90' : ''}`} />
            {p.slot !== undefined && <span className="absolute top-0 left-0 mono text-[10px] px-1" style={{ background: '#0d0d0d', color: '#fff' }}>{String(p.slot).padStart(2, '0')}</span>}
            {r && <span className="absolute inset-x-0 bottom-0 text-[10px] font-semibold py-0.5 bg-ink/80" style={{ color: decisionColor[r.decision] }}>{r.decision}</span>}
            {r && reveal && r.truth !== null && (
              <span className={`absolute top-0.5 right-0.5 text-[9px] px-1 rounded ${truthBad ? 'bg-fail text-ink' : 'bg-pass text-ink'}`}>{truthBad ? 'defect' : 'good'}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export default function LiveScan({ sessionId, records, policy, cloud, patches, memories, heat3d, onShow, selected, isUpload, onRecord, board, goldenUrl }: {
  sessionId: string; records: InspectionRecord[]; policy: Policy | null; cloud: Cloud | null; patches: number | null; memories: number | null;
  heat3d: number[] | null; onShow: (rid: string) => void; selected: InspectionRecord | undefined; isUpload: boolean; onRecord?: (r: InspectionRecord) => void;
  board?: BoardMapT | null; goldenUrl?: string | null;
}) {
  const [labels, setLabels] = useState<'faults' | 'all'>('faults');
  const [mode, setMode] = useState<'tray' | 'upload' | 'camera'>('tray');
  const { notify } = useStore();
  const [lot, setLot] = useState<LotPart[]>([]);
  const [scanned, setScanned] = useState<Record<string, InspectionRecord>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>('done');
  const [live, setLive] = useState<InspectionRecord | null>(null);
  const [reveal, setReveal] = useState(false);
  const [fixed, setFixed] = useState(false);
  const [auto, setAuto] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const [ai, setAi] = useState<{ rid: string; facts: string; vision: { region: string; text: string }[]; mode: string | null } | null>(null);
  const [aiBusy, setAiBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const autoRef = useRef(false);
  const stopAuto = () => { autoRef.current = false; setAuto(false); };

  const freshLot = async () => {
    setErr(null);
    try { const r = await api.newLot(sessionId, 12); setLot(r.lot); setFixed(!!r.fixed); setScanned({}); } catch (e: any) { setErr(e.message); }
  };
  const randomLot = async () => {
    setErr(null);
    try { const r = await api.newLot(sessionId, 12, true); setLot(r.lot); setFixed(false); setScanned({}); } catch (e: any) { setErr(e.message); }
  };
  useEffect(() => {
    api.lot(sessionId).then(r => { if (r.lot.length) { setLot(r.lot); setFixed(!!r.fixed); } else freshLot(); }).catch(() => freshLot());
    setScanned({}); setLive(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const wait = (ms: number) => new Promise(res => setTimeout(res, ms));
  const play = async (fast: boolean) => {
    const step = fast ? 260 : 650;
    for (const p of PHASES) { setPhase(p.key); await wait(p.key === 'compare' ? step + 350 : step); }
    setPhase('done');
  };

  const scan = async (token: string, fast = false) => {
    setBusy(token); setErr(null); setActive(null);
    try {
      const rec = await api.scan(sessionId, token);
      setScanned(s => ({ ...s, [token]: rec }));
      setLive(rec); onShow(rec.id); onRecord?.(rec);
      await play(fast);
      if (!fast) {
        const nf = rec.board?.faults.filter(f => f.level === 'fault').length ?? 0;
        notify(rec.decision === 'PASS' ? `Board ${rec.id.split('-').pop()} passed${rec.board ? `: all ${rec.board.checked} parts checked` : ''}.`
          : `Board ${rec.id.split('-').pop()}: ${rec.decision}${nf ? `, ${nf} component fault${nf > 1 ? 's' : ''}` : ''}. Next: approve it on the Approval step.`,
          rec.decision === 'PASS' ? 'pass' : rec.decision === 'FAIL' ? 'fail' : 'doubt');
      }
      return true;
    } catch (e: any) { setErr(e.message); return false; } finally { setBusy(null); }
  };
  const next = () => lot.find(p => !scanned[p.token]);
  const runAll = async () => {
    autoRef.current = true;
    setAuto(true);
    let p = next();
    const done = new Set<string>();
    while (p && autoRef.current) {
      done.add(p.token);
      if (!(await scan(p.token, true))) break;
      await wait(500);
      p = lot.find(x => !scanned[x.token] && !done.has(x.token));
    }
    stopAuto();
  };

  // show the freshly scanned part animated; any other selected record is shown complete
  const rec = selected && live && selected.id === live.id ? live : selected ?? live ?? undefined;
  const ph: Phase = rec && live && rec.id === live.id ? phase : 'done';
  const remaining = lot.filter(p => !scanned[p.token]).length;
  const scannedList = Object.values(scanned);
  const caughtTruth = useMemo(() => {
    const known = scannedList.filter(r => r.truth !== null);
    const right = known.filter(r => (r.truth === 1 ? r.decision !== 'PASS' : r.decision !== 'FAIL')).length;
    return { known: known.length, right, bad: known.filter(r => r.truth === 1).length };
  }, [scannedList]);

  const askAI = async () => {
    if (!rec) return;
    setAiBusy(true);
    try {
      const r = await api.explain(sessionId, rec.id);
      setAi({ rid: rec.id, facts: r.facts, vision: r.vision, mode: r.mode });
    } catch (e: any) { setErr(e.message); } finally { setAiBusy(false); }
  };

  return (
    <Panel title="Live scan" tone={rec && ph === 'done' ? (rec.decision === 'PASS' ? 'pass' : rec.decision === 'FAIL' ? 'fail' : 'doubt') : undefined} aside={
      <div className="flex items-center gap-2 flex-wrap justify-end">
        <div className="flex rounded-lg border border-line overflow-hidden text-[12px]">
          {(['tray', 'upload', 'camera'] as const).map(m => <button key={m} onClick={() => setMode(m)} className={`px-3 py-1.5 ${mode === m ? 'bg-accent text-ink font-semibold' : 'text-mist hover:text-bone'}`}>{m === 'tray' ? 'Tray' : m === 'upload' ? 'Upload' : 'Camera'}</button>)}
        </div>
        <span className="text-mist text-sm num">{remaining} unscanned on the tray</span>
        <Btn tone="doubt" disabled={!!busy || !remaining} onClick={() => { const p = next(); if (p) scan(p.token); }}>Scan next part</Btn>
        {auto ? <Btn onClick={stopAuto}>Stop</Btn> : <Btn disabled={!!busy || !remaining} onClick={runAll}>Scan the whole tray</Btn>}
        <Btn tone="ghost" disabled={!!busy} onClick={freshLot}>{isUpload ? 'Next uploaded photos' : fixed ? 'Restart the demo tray' : 'Demo tray'}</Btn>
        {!isUpload && <Btn tone="ghost" disabled={!!busy} onClick={randomLot}>Random tray</Btn>}
      </div>}>
      {mode === 'upload' && (
        <div className="mb-4">
          <UploadScan sessionId={sessionId} onError={setErr} onOpen={rid => { setActive(null); onShow(rid); }}
            onResult={async r => { setLive(r); onShow(r.id); onRecord?.(r); setActive(null); await play(true); }} />
        </div>
      )}
      {mode === 'camera' && (
        <div className="mb-4">
          <CameraScan sessionId={sessionId} onError={setErr} onResult={async r => { setLive(r); onShow(r.id); onRecord?.(r); setActive(null); await play(false); }} />
        </div>
      )}
      {mode === 'tray' && <p className="text-sm text-mist mb-3">{fixed
        ? 'The demo tray: the same boards in the same order every time, one for each situation the station handles. What each board is stays hidden until it is scanned.'
        : 'Parts arrive unlabelled. Nobody, including this screen, knows which ones are defective until they are scanned.'}</p>}
      {mode === 'tray' && lot.length ? <Tray lot={lot} scanned={scanned} reveal={reveal} busyToken={busy} onScan={t => scan(t)} onOpen={rid => { setActive(null); onShow(rid); }} />
        : mode === 'tray' ? <div className="text-mist text-sm">{isUpload ? 'All uploaded photos have been scanned.' : 'Loading a tray…'}</div> : null}
      {err && <div className="text-fail text-sm mt-2">{err}</div>}
      {mode === 'tray' && rec?.demo && ph === 'done' && (
        <div className="mt-3 px-3 py-2 border border-line flex flex-wrap items-baseline gap-x-3 gap-y-1" style={{ borderLeft: `4px solid ${rec.demo.asExpected ? 'var(--pass)' : 'var(--fail)'}` }}>
          <span className="label">Board {String(rec.demo.slot).padStart(2, '0')} was</span>
          <span className="font-semibold">{rec.demo.title}</span>
          <span className="text-sm text-mist">expected {rec.demo.expect.join(' or ')} · got <b style={{ color: decisionColor[rec.decision] }}>{rec.decision}</b>{rec.demo.asExpected ? '' : ' (not as expected)'}</span>
        </div>
      )}

      {rec ? (
        <div className="grid xl:grid-cols-[minmax(0,460px)_minmax(0,1fr)] gap-6 mt-5">
          <div>
            <Scanner rec={rec} phase={ph} active={active} setActive={setActive} />
            <div className="text-mist text-xs mt-2 num">{rec.id} · computed in {rec.latency_ms ?? '–'} ms on this station{ph !== 'done' ? ' · replayed slowly so you can follow it' : ''}</div>
          </div>
          <div className="min-w-0 space-y-4">
            <ol className="space-y-1.5">
              {PHASES.map((p, i) => {
                const idx = PHASES.findIndex(x => x.key === ph);
                const state = ph === 'done' || i < idx ? 'done' : i === idx ? 'now' : 'todo';
                const ms = stageMs(rec, p.key);
                return (
                  <li key={p.key} className={`flex gap-3 items-start text-sm transition-opacity ${state === 'todo' ? 'opacity-30' : ''}`}>
                    <span className={`mt-1 w-2.5 h-2.5 rounded-full shrink-0 ${state === 'now' ? 'bg-doubt animate-pulse' : state === 'done' ? 'bg-pass' : 'bg-line'}`} />
                    <div className="min-w-0 flex-1">
                      <div className="flex justify-between gap-3"><span className="font-semibold">{p.title}</span><span className="text-mist num text-xs">{ms != null ? `${ms.toFixed(0)} ms` : ''}</span></div>
                      {state !== 'todo' && <div className="text-mist text-xs truncate">{stageDetail(rec, p.key, patches, memories)}</div>}
                    </div>
                  </li>
                );
              })}
            </ol>
            {ph === 'done' && (
              <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="space-y-4">
                <div className="flex items-baseline gap-4 flex-wrap">
                  <Verdict d={rec.decision} size="xl" />
                  {rec.doubt_reason && <span className="text-doubt font-semibold">{reasonText[rec.doubt_reason]}</span>}
                  {rec.hold_reason && <span className="text-hold font-semibold">{rec.hold_reason}</span>}
                </div>
                <Voice>{rec.explanation}</Voice>
                {policy && rec.decision !== 'HOLD' && <DoubtGauge score={rec.score} tauPass={rec.pass_line ?? policy.tau_pass} tauFail={policy.tau_fail} decision={rec.decision as any} />}
                <Detectors rec={rec} policy={policy} />
                {goldenUrl && <Comparator rec={rec} goldenUrl={goldenUrl} />}
                {!!rec.regions?.length && (
                  <div className="grid gap-2">
                    {rec.regions.map(g => (
                      <button key={g.id} onMouseEnter={() => setActive(g.id)} onMouseLeave={() => setActive(null)}
                        className={`flex gap-3 items-center text-left rounded-xl p-2 bg-raised border ${active === g.id ? 'border-bone' : 'border-transparent'}`}>
                        {g.crop && <img src={g.crop} alt="" className="w-14 h-14 rounded-lg object-cover" />}
                        <div className="min-w-0 text-xs">
                          <div className="font-semibold text-sm" style={{ color: SEV[g.severity] }}>{g.id} · {g.label}</div>
                          <div className="text-mist">{g.severity} · {g.areaPct}% of the part · {g.unusualness}× the pass line</div>
                          <div className="text-mist">{g.realOdds != null ? `regions like this were real defects ${Math.round(g.realOdds * 100)}% of the time` : 'odds not measured yet'}</div>
                          <div className="text-mist/80 truncate" title={g.namedBy}>name: {g.namedBy === 'closest labelled defect of this product' ? 'closest labelled example (a guess)' : 'CLIP zero-shot guess'}</div>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
                {rec.board && <ComponentCheck check={rec.board} board={board ?? null} passed={rec.decision === 'PASS'} />}
                {!rec.board && board?.status === 'building' && <p className="text-xs text-mist">Component map is still being built; component checks start as soon as it is ready.</p>}
                {rec.synthetic && <p className="text-xs text-doubt">Fault lab part: {rec.synthetic} was planted on a real good board. Kept out of all real metrics.</p>}
                <div className="flex flex-wrap gap-2 items-center">
                  <Btn tone="ghost" disabled={aiBusy} onClick={askAI}>{aiBusy ? 'Local AI is looking…' : 'What is wrong with it?'}</Btn>
                  <label className="text-sm text-mist flex items-center gap-2">
                    <input type="checkbox" checked={reveal} onChange={e => setReveal(e.target.checked)} /> Check against dataset truth
                  </label>
                  {reveal && <span className="text-sm num">{rec.truth === null ? 'truth unknown (your photo)' : rec.truth ? `truth: defect (${rec.defect_type})` : 'truth: good'}</span>}
                </div>
                {ai && ai.rid === rec.id && (
                  <div className="rounded-xl bg-raised p-3 text-sm space-y-2">
                    <Voice>{ai.facts}</Voice>
                    {ai.vision.length > 0 && (
                      <div className="border-t border-line pt-2">
                        <div className="text-xs text-mist mb-1">What the local AI sees in each close-up (description only, it does not decide)</div>
                        {ai.vision.map(v => <div key={v.region} className="text-sm"><span className="font-semibold">{v.region}:</span> {v.text}</div>)}
                      </div>
                    )}
                    <div className="text-xs text-mist">{ai.mode ?? 'facts only'} · runs on this station, nothing leaves the plant</div>
                  </div>
                )}
                {reveal && caughtTruth.known > 0 && (
                  <div className="text-xs text-mist num">This tray so far: {caughtTruth.right}/{caughtTruth.known} handled safely (defects not passed, good parts not rejected) · {caughtTruth.bad} were truly defective.</div>
                )}
              </motion.div>
            )}
          </div>
          {cloud && board?.status === 'ready' && board.components && (
            <div className="xl:col-span-2">
              <div className="flex justify-between items-center mb-2">
                <h3 className="text-sm font-semibold">The board in 3D: every component, faults lit up</h3>
                <div className="flex gap-1 text-xs">
                  {(['faults', 'all'] as const).map(l => <button key={l} onClick={() => setLabels(l)} className={`px-2 py-1 rounded-lg ${labels === l ? 'bg-raised text-bone' : 'text-mist'}`}>{l === 'faults' ? 'label faults' : 'label every part'}</button>)}
                </div>
              </div>
              <Suspense fallback={<div className="h-[420px] rounded-xl bg-raised" />}>
                <Board3D cloud={cloud} components={board.components} faults={ph === 'done' ? rec.board?.faults.filter(f => f.level === 'fault') : null}
                  watch={ph === 'done' ? rec.board?.faults.filter(f => f.level === 'watch') : null} verdict={rec.decision}
                  photo={(rec.board as any)?.aligned ?? null} key={rec.id}
                  regions={rec.regions} heat={heat3d} height={460} labels={labels} />
              </Suspense>
              <p className="text-xs text-mist mt-1">Drag to turn the board, hover any part to name it. Boxes are coloured by part type; flagged parts glow in the colour of their problem.</p>
            </div>
          )}
          {cloud && board?.status !== 'ready' && (
            <div className="xl:col-span-2">
              <h3 className="text-sm font-semibold mb-2">Where on the part, in 3D</h3>
              <Suspense fallback={<div className="h-[380px] rounded-xl bg-raised" />}>
                <Twin3D cloud={cloud} heat={heat3d} height={380} cameras={false} regions={ph === 'done' ? rec.regions : null}
                  activeRegion={active} onPickRegion={id => setActive(a => (a === id ? null : id))} />
              </Suspense>
              <p className="text-xs text-mist mt-1">{rec.regions?.length ? 'Drag to turn the part. Each label is pinned where the defect sits on the 3D surface.' : rec.decision === 'PASS' ? 'Nothing to pin: the part looks like the good ones.' : 'No single spot stands out on this part.'}</p>
            </div>
          )}
        </div>
      ) : null}
    </Panel>
  );
}
