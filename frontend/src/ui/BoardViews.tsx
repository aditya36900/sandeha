import React from 'react';
import { BoardCheck, BoardComponent, BoardMapT, CompFault } from '../api';
import { KIND_COLOR, STATUS_COLOR, STATUS_WORD } from './Board3D';

/** The golden board with every component outlined; faults filled. Click a component to select it. */
export function BoardMap2D({ board, faults, selected, onSelect, height }: {
  board: BoardMapT; faults?: CompFault[] | null; selected?: string | null; onSelect?: (id: string) => void; height?: number;
}) {
  const byId = new Map((faults ?? []).map(f => [f.id, f] as const));
  return (
    <div className="relative rounded-xl overflow-hidden bg-ink select-none" style={height ? { height } : undefined}>
      {board.golden && <img src={board.golden} alt="Golden board" className="w-full h-full object-contain" />}
      <svg className="absolute inset-0 w-full h-full" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
        {(board.components ?? []).map(c => {
          const f = byId.get(c.id);
          const [x, y, w, h] = c.bbox.map(v => v * 100);
          const col = f ? STATUS_COLOR[f.status] : KIND_COLOR[c.kind] ?? '#8f97c2';
          return <rect key={c.id} x={x} y={y} width={w} height={h} fill={f ? col : selected === c.id ? 'rgba(242,169,59,0.35)' : 'transparent'}
            fillOpacity={f ? 0.45 : 1} stroke={selected === c.id ? '#f2a93b' : col} strokeWidth={selected === c.id ? 0.6 : 0.3} />;
        })}
        {(faults ?? []).filter(f => f.status === 'EXTRA' && f.bbox).map(f => {
          const [x, y, w, h] = f.bbox!.map(v => v * 100);
          return <rect key={f.id} x={x} y={y} width={w} height={h} fill={STATUS_COLOR.EXTRA} fillOpacity={0.4} stroke={STATUS_COLOR.EXTRA} strokeWidth={0.4} strokeDasharray="1 0.6" />;
        })}
      </svg>
      {onSelect && (board.components ?? []).map(c => {
        const [x, y, w, h] = c.bbox;
        return <button key={c.id} onClick={() => onSelect(c.id)} title={`${c.id} · ${c.kind}`} aria-label={`Select ${c.id}`}
          className="absolute" style={{ left: `${x * 100}%`, top: `${y * 100}%`, width: `${w * 100}%`, height: `${h * 100}%` }} />;
      })}
      {(board.components ?? []).map(c => {
        const f = byId.get(c.id);
        if (!f && selected !== c.id) return null;
        const [x, y] = c.bbox;
        return <span key={c.id} className="absolute -translate-y-full text-[10px] font-semibold px-1 rounded bg-ink/85 pointer-events-none"
          style={{ left: `${x * 100}%`, top: `${y * 100}%`, color: f ? STATUS_COLOR[f.status] : '#f2a93b' }}>{c.id}{f ? ` ${STATUS_WORD[f.status]}` : ''}</span>;
      })}
    </div>
  );
}

export function KindLegend({ board }: { board: BoardMapT }) {
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
      {Object.entries(board.kinds ?? {}).sort((a, b) => b[1] - a[1]).map(([k, n]) => (
        <span key={k} className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm" style={{ background: KIND_COLOR[k] ?? '#8f97c2' }} />{n} {k}</span>
      ))}
    </div>
  );
}

/** Per-component verdicts for one inspected board. */
export function ComponentCheck({ check, board, passed }: { check: BoardCheck; board: BoardMapT | null; passed: boolean }) {
  const kinds = new Map((board?.components ?? []).map(c => [c.id, c.kind] as const));
  const faults = check.faults.filter(f => f.level === 'fault');
  const watch = check.faults.filter(f => f.level === 'watch');
  return (
    <div className="rounded-xl bg-raised p-3">
      <div className="flex justify-between items-baseline gap-3 flex-wrap">
        <div className="font-semibold">Component check</div>
        <div className="text-xs text-mist num">{check.checked} components · {check.ok} as on good boards{check.faults.length ? ` · ${check.faults.length} flagged` : ''}</div>
      </div>
      {!check.faults.length && <p className="text-sm text-pass mt-1">Every component sits where it should and looks like it does on good boards.</p>}
      {faults.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {faults.map(f => (
            <li key={f.id} className="text-sm flex gap-2 items-start">
              <span className="mt-1 w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: STATUS_COLOR[f.status] }} />
              <span><b style={{ color: STATUS_COLOR[f.status] }}>{f.id}</b> <span className="text-mist">{f.status === 'EXTRA' ? '' : kinds.get(f.id) ?? f.kind}</span> · <b>{STATUS_WORD[f.status]}</b>
                {f.why?.[0] && <span className="text-mist"> · {f.why[0]}</span>}</span>
            </li>
          ))}
        </ul>
      )}
      {watch.length > 0 && (
        <p className="text-xs text-mist mt-2">{passed ? 'Watch (the board passed its calibrated check, so these do not reject it): ' : 'Watch: '}
          {watch.map(f => `${f.id} ${STATUS_WORD[f.status]}`).join(', ')}</p>
      )}
    </div>
  );
}
