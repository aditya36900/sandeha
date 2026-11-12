import React, { useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { api } from '../api';
import { useStore } from '../store';
import { Panel, decisionColor } from '../ui/bits';
import { STATUS_COLOR } from '../ui/Board3D';
import { PageHead, usePoll } from '../room/common';
import { LinePicker, Measured, prettyStatus, useSid } from './common';

const KIND_SHORT: Record<string, string> = { resistor: 'R', capacitor: 'C', IC: 'U', transistor: 'Q', 'diode / LED': 'D', inductor: 'L', connector: 'J', 'hole / pad': 'H', 'metal part': 'M', other: 'X' };

/** 0..2 drift -> colour: calm grey-blue, warming through amber to red at the limit and beyond. */
function cellColor(v: number | null, status?: string | null) {
  if (v == null) return 'transparent';
  if (status && status !== 'OK') return STATUS_COLOR[status] ?? 'var(--fail)';
  const t = Math.min(1, v);                       // 1 = at the learned limit
  const h = 215 - 215 * t * 0.85;                 // blue -> orange
  const l = 24 + 36 * t;
  return `hsl(${h} ${40 + 45 * t}% ${l}%)`;
}

export default function Pulse() {
  const [sid, setSid] = useSid();
  const { setAct, setSelectedRecord } = useStore();
  const [p] = usePoll(() => (sid ? api.pulse(sid, 80) : Promise.resolve(null)), 6000, [sid]);
  const [hover, setHover] = useState<{ r: number; c: number } | null>(null);
  const [kind, setKind] = useState<string>('all');
  const rows = useMemo(() => (p?.components ?? []).filter((r: any) => kind === 'all' || r.kind === kind), [p, kind]);
  const kinds: string[] = useMemo(() => Array.from(new Set((p?.components ?? []).map((r: any) => r.kind))), [p]);
  if (!p) return <PageHead title="Line pulse" sub="Loading…" />;
  const boards = p.boards as any[];
  const open = (rid: string) => { setSelectedRecord(rid); setAct('approval'); };
  const hv = hover ? rows[hover.r]?.cells[hover.c] : null;
  const hb = hover ? boards[hover.c] : null;
  return (
    <div className="space-y-4">
      <PageHead title="Line pulse" sub="Every component on the board, board after board. A row warming up is a part drifting from the golden board before it becomes a defect; a lit cell is a fault. Columns arrive as boards are scanned."
        aside={<div className="flex gap-2 items-center"><LinePicker sid={sid} setSid={setSid} /><Measured /></div>} />

      <Panel title={`Last ${p.stream.length} verdicts`}>
        <div className="flex gap-[3px] items-end h-8">
          {p.stream.map((s: any, i: number) => (
            <motion.button key={s.id} initial={{ height: 4, opacity: 0 }} animate={{ height: s.decision === 'PASS' ? 10 : s.decision === 'DOUBT' ? 20 : 32, opacity: 1 }} transition={{ delay: i * 0.01 }}
              onClick={() => open(s.id)} title={`${s.id} · ${s.decision}`} className="flex-1 min-w-[3px] rounded-sm" style={{ background: decisionColor[s.decision as 'PASS'] }} />
          ))}
        </div>
        <div className="flex gap-4 mt-2 text-xs text-mist"><span>short = pass</span><span>medium = doubt</span><span>tall = fail / hold</span></div>
      </Panel>

      <Panel title="Component health matrix" aside={
        <div className="flex gap-2 items-center text-xs">
          <select value={kind} onChange={e => setKind(e.target.value)} className="bg-raised border border-line rounded-md px-2 py-1" aria-label="Part type">
            <option value="all">all part types</option>{kinds.map(k => <option key={k} value={k}>{k}</option>)}
          </select>
          <span className="text-mist">{boards.length} boards · {rows.length} components</span>
        </div>}>
        {!boards.length ? <p className="text-mist text-sm">No component-checked boards yet. Scan some on the line.</p> : (
          <div className="overflow-x-auto">
            <div className="grid" style={{ gridTemplateColumns: `72px repeat(${boards.length}, minmax(9px, 1fr)) 56px`, gap: '2px' }}>
              <div />
              {boards.map((b: any, c: number) => (
                <button key={b.id} onClick={() => open(b.id)} title={`${b.id} · ${b.decision}`} className="h-2 rounded-sm" style={{ background: decisionColor[b.decision as 'PASS'], opacity: hover && hover.c !== c ? 0.35 : 1 }} />
              ))}
              <div className="text-[10px] text-mist text-right pr-1">faults</div>
              {rows.map((r: any, ri: number) => (
                <React.Fragment key={r.id}>
                  <div className={`text-xs num pr-2 leading-4 ${hover?.r === ri ? 'text-bone' : 'text-mist'}`} title={r.kind}><b className="text-bone">{r.id}</b> <span className="text-[10px]">{KIND_SHORT[r.kind] ?? ''}</span></div>
                  {r.cells.map((cell: any, c: number) => (
                    <motion.div key={c} initial={{ scaleY: 0 }} animate={{ scaleY: 1 }} transition={{ delay: Math.min(0.6, c * 0.008) }}
                      onMouseEnter={() => setHover({ r: ri, c })} onMouseLeave={() => setHover(null)} onClick={() => open(boards[c].id)}
                      className="h-4 rounded-[2px] cursor-pointer"
                      style={{ background: cellColor(cell?.v ?? null, cell?.status), outline: hover && (hover.r === ri || hover.c === c) ? '1px solid rgb(var(--bone-rgb) / 0.5)' : 'none',
                        opacity: hover && hover.r !== ri && hover.c !== c ? 0.45 : 1, boxShadow: cell?.level === 'fault' ? `0 0 0 1px ${STATUS_COLOR[cell.status] ?? 'var(--fail)'}` : undefined }} />
                  ))}
                  <div className="text-xs num text-right pr-1 leading-4" style={{ color: r.faults ? 'var(--fail)' : 'var(--mist)' }}>{r.faults || '·'}</div>
                </React.Fragment>
              ))}
            </div>
            <div className="flex items-center gap-4 mt-3 text-xs text-mist flex-wrap">
              <span className="flex items-center gap-1.5"><i className="w-10 h-2 rounded-sm" style={{ background: 'linear-gradient(90deg, hsl(215 40% 24%), hsl(110 62% 42%), hsl(32 85% 60%))' }} /> drift from the golden board, up to the learned limit</span>
              {Object.entries(STATUS_COLOR).map(([k, col]) => <span key={k} className="flex items-center gap-1"><i className="w-2.5 h-2.5 rounded-[2px]" style={{ background: col }} />{prettyStatus(k)}</span>)}
            </div>
            <div className="h-6 mt-2 text-xs">
              {hv && hb ? <span><b>{rows[hover!.r].id}</b> on <b className="num">{hb.id}</b> ({hb.decision}): offset {hv.offset} px · lightness {hv.dL > 0 ? '+' : ''}{hv.dL} · {hv.status === 'OK' ? 'as on good boards' : `${prettyStatus(hv.status)}${hv.level === 'watch' ? ' (watch)' : ''}`} — click to open the dossier</span>
                : <span className="text-mist">Hover a cell. Rows are ordered by trouble: most faults first, then highest average drift.</span>}
            </div>
          </div>
        )}
      </Panel>

      <Panel title="Defect atlas" aside={<span className="text-xs text-mist">{p.atlas.reduce((a: number, g: any) => a + g.count, 0)} close-ups, grouped by what they looked most like</span>}>
        {!p.atlas.length ? <p className="text-mist text-sm">No defect regions found yet.</p> : (
          <div className="space-y-4">
            {p.atlas.map((g: any) => (
              <div key={g.label}>
                <div className="flex items-baseline gap-2 mb-1.5"><span className="text-sm font-medium">{g.label}</span><span className="text-xs text-mist num">{g.count}</span></div>
                <div className="flex flex-wrap gap-1.5">
                  {g.items.map((it: any, i: number) => (
                    <motion.button key={it.crop + i} initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: i * 0.02 }}
                      onClick={() => open(it.part)} title={`${it.part} · ${it.severity}${it.component ? ` · ${it.component}` : ''}${it.synthetic ? ' · fault lab' : ''}`}
                      className="relative w-16 h-16 rounded-md overflow-hidden border border-line hover:border-bone">
                      <img src={it.crop} alt="" className="w-full h-full object-cover" loading="lazy" />
                      <span className="absolute left-0 bottom-0 right-0 h-1" style={{ background: it.severity === 'critical' ? 'var(--fail)' : it.severity === 'major' ? 'var(--doubt)' : 'var(--mist)' }} />
                      {it.component && <span className="absolute top-0.5 left-0.5 text-[9px] num px-1 rounded bg-ink/80">{it.component}</span>}
                    </motion.button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
