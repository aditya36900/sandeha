import React from 'react';
import { InspectionRecord, Policy } from '../api';

/** The two independent detectors and whether they agree. */
export default function Detectors({ rec, policy }: { rec: InspectionRecord; policy: Policy | null }) {
  const s = rec.signals;
  if (!s || !policy) return null;
  const tp = rec.pass_line ?? policy.tau_pass, tf = policy.tau_fail;
  const bar = (v: number) => Math.min(100, (100 * v) / (tf * 1.6));
  const patchAbove = s.patchMemory > tp, goldenStrong = s.goldenDeviation > 0.4 * (tf - tp);
  const agree = s.detectors < 2 ? null : patchAbove === goldenStrong;
  return (
    <div className="panel p-3">
      <div className="flex justify-between items-baseline mb-2">
        <span className="label">Two detectors</span>
        {agree === null ? <span className="label">golden board not ready</span>
          : <span className="label" style={{ color: agree ? 'var(--pass)' : 'var(--doubt)' }}>{agree ? 'agree' : 'disagree'}</span>}
      </div>
      {[
        ['Patch memory (DINOv2)', s.patchMemory, 'how far each patch sits from the nearest good patch'],
        ['Golden-board deviation', s.goldenDeviation, 'per-pixel distance from the 30 aligned good boards, in spreads'],
        ['Fused (decides)', s.fused, 'one map, so the lines, heatmap and components all agree'],
      ].map(([name, v, hint]) => (
        <div key={name as string} className="mb-1.5">
          <div className="flex justify-between text-xs"><span>{name}</span><span className="num text-mist">{(v as number).toFixed(3)}</span></div>
          <div className="relative h-1.5 rounded-full bg-raised mt-0.5">
            <div className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${bar(v as number)}%`, background: name === 'Fused (decides)' ? 'var(--accent)' : 'var(--mist)' }} />
            <span className="absolute -top-0.5 w-px h-2.5 bg-doubt" style={{ left: `${bar(tp)}%` }} />
            <span className="absolute -top-0.5 w-px h-2.5 bg-fail" style={{ left: `${bar(tf)}%` }} />
          </div>
          <div className="text-[10px] text-mist">{hint}</div>
        </div>
      ))}
      <div className="text-[10px] text-mist mt-1">Ticks: pass line (amber) and fail line (red). {agree === false ? 'When the detectors disagree the board leans to doubt: a person decides.' : ''}</div>
    </div>
  );
}
