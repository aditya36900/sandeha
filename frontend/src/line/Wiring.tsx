import React, { useEffect, useState } from 'react';
import { api } from '../api';
import { Panel, pct } from '../ui/bits';
import { Kpi, PageHead } from '../room/common';
import { Measured } from './common';

const NAMES: Record<string, string> = { pcb1: 'Ultrasonic sensor (front)', pcb2: 'Ultrasonic sensor (back)', pcb3: 'IR sensor module', pcb4: 'Li-ion charger board' };
const ORDER = ['pcb1', 'pcb2', 'pcb3', 'pcb4'];
const tone = (v: number, good: number, ok: number) => (v >= good ? 'var(--pass)' : v >= ok ? 'var(--doubt)' : 'var(--fail)');

/** Wiring map: the copper read from the good boards, and how well connection faults can be found on it. */
export default function Wiring() {
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [k, setK] = useState('pcb4');
  useEffect(() => { api.wiring().then(r => { setD(r); if (!r[k]) setK(Object.keys(r)[0]); }).catch(e => setErr(e.message)); /* eslint-disable-next-line */ }, []);
  if (err) return <PageHead title="Wiring map" sub={err} />;
  if (!d) return <PageHead title="Wiring map" sub="Loading…" />;
  const keys = ORDER.filter(x => d[x]);
  const r = d[k];
  const pl = r.planted;
  return (
    <div className="space-y-4">
      <PageHead title="Wiring map: what is connected to what"
        sub="Read from 30 good photos at full resolution, with no design file: every solder pad, and every piece of copper visible under the coating. Pads on the same piece of copper are wired together. Each colour is one conductor."
        aside={<Measured />} />
      <div className="flex flex-wrap gap-2">
        {keys.map(x => (
          <button key={x} onClick={() => setK(x)} className="btn px-4 h-9 text-sm border border-line" style={x === k ? { background: 'var(--bone)', color: 'var(--surface)' } : { background: 'var(--surface)' }}>
            <span className="mono text-[11px] opacity-70 mr-2">{x.toUpperCase()}</span>{NAMES[x] ?? x}
          </button>
        ))}
      </div>
      <div className="grid xl:grid-cols-[1.35fr_1fr] gap-4">
        <Panel title="Top-side copper and pads">
          <img src={`/api/wiring/img/${k}.jpg`} alt={`Wiring map of ${k}`} className="w-full block" />
          <p className="text-xs text-mist mt-2">
            White boxes are pads (solder joints, IC pins, test pads). Coloured areas are copper seen through the coating; dark areas have no copper on this side.
            {r.copperVisible ? '' : ' On this board the copper does not show through the coating, so only the pads could be mapped.'}
          </p>
        </Panel>
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-3">
            <Kpi label="Pads" value={r.pads} />
            <Kpi label="Conductors" value={r.conductors} />
            <Kpi label="Pad-to-pad links" value={r.links} />
          </div>
          <Panel title="Can it find connection faults? Planted-fault test">
            <table className="w-full text-sm num">
              <thead className="text-left text-xs text-mist"><tr><th className="py-1.5">Planted on good boards</th><th className="text-right">Tried</th><th className="text-right">Caught</th><th className="text-right">Right place</th></tr></thead>
              <tbody>
                {[['short', 'Solder bridge between two pads'], ['open', 'Joint with its solder gone'], ['cut', 'Wire cut right across']].map(([key, title]) => (
                  <tr key={key} className="border-t border-line">
                    <td className="py-1.5">{title}</td><td className="text-right text-mist">{pl[key].n}</td>
                    <td className="text-right font-semibold" style={{ color: pl[key].n ? tone(pl[key].caught, 0.9, 0.7) : undefined }}>{pl[key].n ? pct(pl[key].caught, 0) : '–'}</td>
                    <td className="text-right">{pl[key].n ? pct(pl[key].located, 0) : '–'}</td>
                  </tr>
                ))}
                <tr className="border-t-2" style={{ borderColor: 'var(--bone)' }}>
                  <td className="py-1.5">False alarms on {r.goodBoards} good boards</td><td /><td className="text-right font-semibold" style={{ color: tone(1 - r.falseAlarms.any, 0.97, 0.9) }}>{pct(r.falseAlarms.any, 0)}</td>
                  <td className="text-right text-xs text-mist">short {pct(r.falseAlarms.short, 0)} · open {pct(r.falseAlarms.open, 0)} · wire {pct(r.falseAlarms.wire, 0)}</td>
                </tr>
              </tbody>
            </table>
            <p className="text-xs text-mist mt-2">Faults were painted onto held-out good boards, so the truth is known. The public dataset has no labelled opens or shorts.</p>
          </Panel>
          <Panel title="Where this stands" tone="doubt">
            <ul className="text-sm list-disc pl-5 space-y-1.5">
              <li><b>Not switched on for verdicts.</b> With these false-alarm rates it would wrongly stop good boards, so it does not change PASS / FAIL today. This page reports what was measured.</li>
              <li><b>Bridges and missing solder are findable</b> from a photo. <b>A cut wire is not</b>, reliably: a hairline break changes too few pixels.</li>
              <li><b>The map is one side only.</b> Copper on the other side, vias and anything under a part are invisible, so two conductors shown as separate may be joined elsewhere. Clearance rings around pads are only a few pixels wide at this photo size.</li>
              <li><b>What would make it exact:</b> the board's design files (Gerber or netlist) to compare against, a sharper camera, or an electrical test. A photo cannot prove that a joint conducts.</li>
            </ul>
          </Panel>
        </div>
      </div>
    </div>
  );
}
