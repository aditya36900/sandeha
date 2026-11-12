import React, { useState } from 'react';
import { api, BoardMapT, InspectionRecord } from '../api';
import { Btn, Panel } from './bits';
import { useStore } from '../store';
import { BoardMap2D, KindLegend } from './BoardViews';

const FAULTS: [string, string][] = [
  ['missing', 'Missing part'], ['shifted', 'Placed in the wrong position'], ['rotated', 'Rotated / reversed (polarity)'],
  ['burnt', 'Burnt'], ['solder_bridge', 'Solder bridge / excess'], ['solder_dry', 'Dry / insufficient joint'],
];

/** The component map, and a rehearsal bench: plant one known fault on one component and scan the board for real. */
export default function FaultLab({ sessionId, board, onRecord }: { sessionId: string; board: BoardMapT; onRecord: (r: InspectionRecord) => void }) {
  const [sel, setSel] = useState<string | null>(null);
  const { notify } = useStore();
  const [kind, setKind] = useState('missing');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const comp = board.components?.find(c => c.id === sel);
  const run = async () => {
    if (!sel) return;
    setBusy(true); setMsg(null);
    try {
      const r = await api.faultLab(sessionId, sel, kind);
      const f = r.board?.faults.find(x => x.id === sel);
      setMsg(f ? `Caught: ${sel} flagged as ${f.status.toLowerCase().replace('_', ' ')}. Board verdict ${r.decision}.`
        : `Missed: ${sel} was not flagged. Board verdict ${r.decision}. Honest result, see the measured rates below.`);
      onRecord(r);
      notify(f ? `Fault lab: ${sel} ${kind.replace('_', ' ')} was caught.` : `Fault lab: ${sel} ${kind.replace('_', ' ')} was missed.`, f ? 'pass' : 'doubt');
    } catch (e: any) { setMsg(e.message); } finally { setBusy(false); }
  };
  const hist = (board.components ?? []).filter(c => Object.keys(c.history).length).sort((a, b) =>
    Object.values(b.history).reduce((x, y) => x + y, 0) - Object.values(a.history).reduce((x, y) => x + y, 0)).slice(0, 6);
  return (
    <Panel title="Component map and fault lab" aside={<span className="text-xs text-mist">{board.components?.length} components · calibrated on {board.calibration}</span>}>
      <div className="grid lg:grid-cols-[minmax(0,520px)_1fr] gap-5">
        <div>
          <BoardMap2D board={board} selected={sel} onSelect={setSel} />
          <div className="mt-2"><KindLegend board={board} /></div>
          {board.classifier && (
            <p className="text-[11px] text-mist mt-2">Part types come from a classifier trained on {board.classifier.train} photographed SMD parts ({board.classifier.dataset}); it is right {Math.round(board.classifier.holdoutAccuracy * 100)}% of the time on {board.classifier.holdout} held-out photos (inductors are its weak spot). Connectors and holes are named by shape.</p>
          )}
        </div>
        <div className="space-y-4 text-sm">
          <div>
            <div className="font-semibold mb-1">Rehearse a fault</div>
            <p className="text-mist text-xs mb-2">Click a component on the board, pick a fault, and I plant it on a real good board I have never inspected, then scan that board like any other. The part is marked synthetic and kept out of the real numbers.</p>
            <div className="flex flex-wrap gap-2 items-center">
              <span className="px-2 py-1.5 rounded-lg bg-raised num">{comp ? `${comp.id} · ${comp.kind}` : 'no component selected'}</span>
              <select value={kind} onChange={e => setKind(e.target.value)} className="bg-raised rounded-lg px-2 py-1.5" aria-label="Fault">
                {FAULTS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}
              </select>
              <Btn tone="doubt" disabled={!sel || busy} onClick={run}>{busy ? 'Planting and scanning…' : 'Plant and scan'}</Btn>
            </div>
            {msg && <p className="mt-2">{msg}</p>}
            {kind === 'solder_dry' && <p className="text-xs text-doubt mt-2">Measured: dry joints are not detectable from a single top-down photo; normal solder shine varies more than a dull joint changes it. Real AOI machines use angled, multi-colour ring lights for this.</p>}
          </div>
          <div>
            <div className="font-semibold mb-1">Which components fail on this line</div>
            {hist.length ? (
              <ul className="space-y-1">
                {hist.map(c => (
                  <li key={c.id} className="flex justify-between gap-3"><span><b>{c.id}</b> <span className="text-mist">{c.kind}</span></span>
                    <span className="text-mist text-xs">{Object.entries(c.history).map(([k, v]) => `${v}× ${k.toLowerCase().replace('_', ' ')}`).join(', ')}</span></li>
                ))}
              </ul>
            ) : <p className="text-mist text-xs">No component faults on real boards yet ({board.boardsChecked ?? 0} boards checked).</p>}
          </div>
        </div>
      </div>
    </Panel>
  );
}
