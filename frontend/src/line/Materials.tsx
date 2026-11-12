import React from 'react';
import { api } from '../api';
import { Panel } from '../ui/bits';
import { KIND_COLOR } from '../ui/Board3D';
import { Chip, Kpi, PageHead, usePoll } from '../room/common';
import { LinePicker, Simulated, useSid } from './common';

const TONE: Record<string, string> = { OK: 'var(--pass)', LOW: 'var(--doubt)', 'BAKE BEFORE USE': 'var(--fail)' };

export default function Materials() {
  const [sid, setSid] = useSid();
  const [m] = usePoll(() => (sid ? api.materials(sid) : Promise.resolve(null)), 15000, [sid]);
  const f = (m?.feeders ?? []) as any[];
  return (
    <div className="space-y-5">
      <PageHead title="Materials" sub="Feeders, reels and moisture-sensitive devices for this board. A wrong reel, an empty feeder or an expired moisture-sensitive part are classic causes of the faults this station sees."
        aside={<div className="flex gap-2 items-center"><LinePicker sid={sid} setSid={setSid} /><Simulated>line context</Simulated></div>} />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi label="Feeders" value={f.length} />
        <Kpi label="Low reels" value={f.filter(x => x.status === 'LOW').length} tone="var(--doubt)" />
        <Kpi label="Moisture-sensitive reels" value={f.filter(x => x.msl).length} />
        <Kpi label="Must bake before use" value={f.filter(x => x.status === 'BAKE BEFORE USE').length} tone="var(--fail)" />
      </div>
      <Panel title="Feeder list">
        <div className="overflow-x-auto">
          <table className="w-full text-sm num">
            <thead className="text-mist text-xs text-left"><tr><th className="py-1">Slot</th><th>Part</th><th>Placed at</th><th>Per board</th><th>Reel</th><th>Boards left</th><th>MSL</th><th>Floor life left</th><th>Status</th></tr></thead>
            <tbody>
              {f.map(x => (
                <tr key={x.slot} className="border-t border-line">
                  <td className="py-2 font-semibold">{x.slot}</td>
                  <td><span className="inline-block w-2.5 h-2.5 rounded-sm mr-1.5 align-middle" style={{ background: KIND_COLOR[x.kind] ?? '#8f97c2' }} />{x.package}</td>
                  <td className="text-xs">{x.references.join(', ')}</td>
                  <td>{x.perBoard}</td>
                  <td className="min-w-[120px]">
                    <div className="h-1.5 bg-line rounded-full"><div className="h-full rounded-full" style={{ width: `${(100 * x.left) / x.reelSize}%`, background: TONE[x.status === 'BAKE BEFORE USE' ? 'OK' : x.status] }} /></div>
                    <div className="text-[11px] text-mist">{x.left.toLocaleString()} / {x.reelSize.toLocaleString()}</div>
                  </td>
                  <td>{x.boardsLeft.toLocaleString()}</td>
                  <td>{x.msl ?? '—'}</td>
                  <td>{x.floorLeftHours == null ? '—' : x.floorLeftHours < 0 ? <span className="text-fail">expired {Math.abs(x.floorLeftHours).toFixed(0)} h ago</span> : `${x.floorLeftHours.toFixed(0)} h of ${x.floorLifeHours} h`}</td>
                  <td><Chip tone={TONE[x.status]}>{x.status.toLowerCase()}</Chip></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-mist mt-2">{m?.note}</p>
      </Panel>
      <Panel title="Why it matters to inspection">
        <ul className="text-sm list-disc pl-5 space-y-1">
          <li><b>Wrong part</b> faults usually mean a reel was loaded on the wrong feeder: check the feeder list against the bill of materials.</li>
          <li><b>Missing parts</b> cluster on a feeder that ran empty or a nozzle that stopped picking.</li>
          <li><b>Moisture-sensitive parts</b> (ICs, LEDs, transistors) past their floor life can crack or delaminate in reflow ("popcorning"); J-STD-033 says bake before use.</li>
        </ul>
      </Panel>
    </div>
  );
}
