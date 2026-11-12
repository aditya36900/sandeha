import React, { Suspense, lazy, useState } from 'react';
import { useStore } from '../store';
import { Panel } from '../ui/bits';
import { BoardMap2D, KindLegend } from '../ui/BoardViews';
import { KIND_COLOR } from '../ui/Board3D';
import { PageHead } from '../room/common';
import { LinePicker, Measured, prettyStatus, useBoardMap, useSid } from './common';

const Board3D = lazy(() => import('../ui/Board3D'));

/** The component library this station learned for the board: every part, its type, footprint and failure history. */
export default function Bom() {
  const [sid, setSid] = useSid();
  const { views } = useStore();
  const board = useBoardMap(sid);
  const [sel, setSel] = useState<string | null>(null);
  const [labels, setLabels] = useState<'faults' | 'all'>('all');
  const cloud = sid ? views[sid]?.cloud ?? null : null;
  const comps = board?.components ?? [];
  return (
    <div className="space-y-5">
      <PageHead title="Component library" sub="What this station learned about the board, without labels: every component, its type (and how sure), its footprint, how it was named, and how often it has failed on this line."
        aside={<div className="flex gap-2 items-center"><LinePicker sid={sid} setSid={setSid} /><Measured /></div>} />
      {board?.status !== 'ready' ? <Panel><p className="text-mist">{board?.status === 'building' ? 'Building the component map…' : 'No component map for this line (not a circuit board).'}</p></Panel> : (
        <>
          <div className="grid xl:grid-cols-2 gap-5">
            <Panel title={`Golden board · ${comps.length} components`} aside={<KindLegend board={board} />}>
              <BoardMap2D board={board} selected={sel} onSelect={setSel} />
              {board.classifier && <p className="text-[11px] text-mist mt-2">Types: classifier on {board.classifier.train} photographed parts, {Math.round(board.classifier.holdoutAccuracy * 100)}% right on {board.classifier.holdout} held-out photos. Normal ranges calibrated on {board.calibration}.</p>}
            </Panel>
            {cloud && (
              <Panel title="In 3D (real KiCad models)" aside={<div className="flex gap-1 text-xs">{(['all', 'faults'] as const).map(l => <button key={l} onClick={() => setLabels(l)} className={`px-2 py-1 rounded-lg ${labels === l ? 'bg-raised' : 'text-mist'}`}>{l === 'all' ? 'label every part' : 'no labels'}</button>)}</div>}>
                <Suspense fallback={<div className="h-[420px] rounded-xl bg-raised" />}>
                  <Board3D cloud={cloud} components={comps} height={420} labels={labels} realistic />
                </Suspense>
              </Panel>
            )}
          </div>
          <Panel title="Every component">
            <div className="overflow-x-auto">
              <table className="w-full text-sm num">
                <thead className="text-mist text-xs text-left"><tr><th className="py-1">Ref</th><th>Type</th><th>Sure</th><th>Named by</th><th>Footprint</th><th>Area</th><th>3D</th><th>Failures on this line</th></tr></thead>
                <tbody>
                  {comps.map(c => (
                    <tr key={c.id} onClick={() => setSel(c.id)} className={`border-t border-line cursor-pointer ${sel === c.id ? 'bg-raised' : 'hover:bg-raised/50'}`}>
                      <td className="py-1.5 font-semibold">{c.id}</td>
                      <td><span className="inline-block w-2.5 h-2.5 rounded-sm mr-1.5 align-middle" style={{ background: KIND_COLOR[c.kind] }} />{c.kind}</td>
                      <td>{Math.round(c.kindConfidence * 100)}%</td>
                      <td className="text-xs text-mist">{c.namedBy}</td>
                      <td className="text-xs">{(c.bbox[2] * 100).toFixed(1)} × {(c.bbox[3] * 100).toFixed(1)} % of photo</td>
                      <td className="text-xs">{c.areaPct}%</td>
                      <td className="text-xs">{c.box3d ? 'pinned' : '—'}</td>
                      <td className="text-xs">{Object.keys(c.history).length ? Object.entries(c.history).map(([k, v]) => `${v}× ${prettyStatus(k)}`).join(', ') : <span className="text-mist">none</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}
