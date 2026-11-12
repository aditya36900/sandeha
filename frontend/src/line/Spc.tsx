import React, { useEffect, useState } from 'react';
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../api';
import { Panel } from '../ui/bits';
import { BoardMap2D } from '../ui/BoardViews';
import { PageHead } from '../room/common';
import { LinePicker, Measured, useBoardMap, useSid } from './common';

/** Statistical process control per component: is a placement head drifting, is a part getting darker? */
export default function Spc() {
  const [sid, setSid] = useSid();
  const board = useBoardMap(sid);
  const [comp, setComp] = useState<string | null>(null);
  const [d, setD] = useState<any | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!comp && board?.components?.length) setComp(board.components.find(c => c.kind === 'IC')?.id ?? board.components[0].id);
  }, [board, comp]);
  useEffect(() => {
    if (!sid || !comp) return;
    setErr(null);
    api.spc(sid, comp).then(setD).catch(e => setErr(e.message));
  }, [sid, comp]);
  const pts = (d?.points ?? []).map((p: any, i: number) => ({ ...p, i: i + 1 }));
  return (
    <div className="space-y-5">
      <PageHead title="Process control (SPC)" sub="Every component's placement offset and colour, board after board, against limits learned from separate good boards. A drift here is a pick-and-place head or a reflow zone going out of tune before it makes defects."
        aside={<div className="flex gap-2 items-center"><LinePicker sid={sid} setSid={s => { setSid(s); setComp(null); }} /><Measured /></div>} />
      <div className="grid xl:grid-cols-[minmax(0,460px)_1fr] gap-5 items-start">
        <Panel title="Pick a component">
          {board?.status === 'ready' ? <BoardMap2D board={board} selected={comp} onSelect={setComp} /> : <p className="text-mist text-sm">Component map not ready.</p>}
          <select value={comp ?? ''} onChange={e => setComp(e.target.value)} className="mt-3 bg-raised rounded-lg px-2 py-1.5 text-sm w-full" aria-label="Component">
            {(board?.components ?? []).map(c => <option key={c.id} value={c.id}>{c.id} · {c.kind}</option>)}
          </select>
        </Panel>
        <div className="space-y-5 min-w-0">
          {err && <p className="text-fail">{err}</p>}
          {d && (
            <>
              <Panel title={`${d.component} · ${d.kind}: placement offset (px)`} aside={<span className="text-xs text-mist">{pts.length} boards · limit from {d.calibration}</span>}>
                {pts.length ? (
                  <div className="h-56">
                    <ResponsiveContainer>
                      <LineChart data={pts} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
                        <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" />
                        <XAxis dataKey="i" tick={{ fill: 'var(--mist)', fontSize: 11 }} />
                        <YAxis tick={{ fill: 'var(--mist)', fontSize: 11 }} />
                        <Tooltip contentStyle={{ background: 'var(--surface)', border: 'none', borderRadius: 12 }} labelFormatter={i => pts[Number(i) - 1]?.part ?? ''} />
                        <ReferenceLine y={d.limits.offsetUCL} stroke="var(--fail)" strokeDasharray="4 4" label={{ value: 'limit', fill: 'var(--fail)', fontSize: 10, position: 'insideTopRight' }} />
                        {d.limits.offsetCentre != null && <ReferenceLine y={d.limits.offsetCentre} stroke="var(--mist)" strokeDasharray="2 2" />}
                        <Line dataKey="offset" stroke="var(--doubt)" strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                ) : <p className="text-mist text-sm">No boards measured yet for this component. Scan some on the line.</p>}
              </Panel>
              <Panel title={`${d.component}: colour change vs the golden board (ΔL*)`}>
                {pts.length ? (
                  <div className="h-48">
                    <ResponsiveContainer>
                      <LineChart data={pts} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
                        <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" />
                        <XAxis dataKey="i" tick={{ fill: 'var(--mist)', fontSize: 11 }} />
                        <YAxis tick={{ fill: 'var(--mist)', fontSize: 11 }} />
                        <Tooltip contentStyle={{ background: 'var(--surface)', border: 'none', borderRadius: 12 }} />
                        <ReferenceLine y={d.limits.dLLCL} stroke="var(--fail)" strokeDasharray="4 4" label={{ value: 'burn limit', fill: 'var(--fail)', fontSize: 10, position: 'insideBottomRight' }} />
                        <ReferenceLine y={0} stroke="var(--mist)" strokeDasharray="2 2" />
                        <Line dataKey="dL" stroke="var(--hold)" strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                ) : <p className="text-mist text-sm">—</p>}
              </Panel>
              <Panel title="Control rules">
                {d.rules.length ? <ul className="list-disc pl-5 text-sm text-doubt">{d.rules.map((r: string) => <li key={r}>{r}</li>)}</ul>
                  : <p className="text-sm text-pass">In control: no Western Electric style rule is triggered (8 above centre, 7 rising, 2 of 3 near the limit).</p>}
              </Panel>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
