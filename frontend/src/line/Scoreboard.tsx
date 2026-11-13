import React, { useEffect, useState } from 'react';
import { api } from '../api';
import { Panel, pct } from '../ui/bits';
import { Kpi, PageHead } from '../room/common';
import { Measured } from './common';

const NAMES: Record<string, string> = { pcb1: 'Ultrasonic sensor (front)', pcb2: 'Ultrasonic sensor (back)', pcb3: 'IR sensor module', pcb4: 'Li-ion charger board' };
const ORDER = ['pcb1', 'pcb2', 'pcb3', 'pcb4'];
const f1 = (x: number) => (100 * x).toFixed(1);

function Bar({ right, asked, wrong }: { right: number; asked: number; wrong: number }) {
  const n = right + asked + wrong || 1;
  return (
    <div className="flex h-3 w-full overflow-hidden bg-raised" title={`${right} right alone · ${asked} sent to a person · ${wrong} wrong`}>
      <i style={{ width: `${(100 * right) / n}%`, background: 'var(--pass)' }} />
      <i style={{ width: `${(100 * asked) / n}%`, background: 'var(--doubt)' }} />
      <i style={{ width: `${(100 * wrong) / n}%`, background: 'var(--fail)' }} />
    </div>
  );
}

/** Scoreboard: counted right / wrong / asked-a-person calls on every held-out board, next to published methods. */
export default function Scoreboard() {
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.benchmark().then(setD).catch(e => setErr(e.message)); }, []);
  if (err) return <PageHead title="Scoreboard" sub={err} />;
  if (!d) return <PageHead title="Scoreboard" sub="Loading…" />;
  const keys = ORDER.filter(k => d.ours[k]);
  const rows = keys.map(k => d.ours[k]);
  const sum = (fn: (r: any) => number) => rows.reduce((a: number, r: any) => a + fn(r), 0);
  const N = sum(r => r.boards), right = sum(r => r.decidedAloneAndRight), asked = sum(r => r.sentToPerson);
  const passedBad = sum(r => r.defective.wronglyPassed), rejGood = sum(r => r.good.wronglyRejected);
  const naiveBad = sum(r => r.singleThreshold.stationPreset.wronglyPassed), naiveGood = sum(r => r.singleThreshold.stationPreset.wronglyRejected);
  const acc = (r: any) => 1 - (r.singleThreshold.stationPreset.wronglyPassed + r.singleThreshold.stationPreset.wronglyRejected) / r.boards;
  const accAll = 1 - (naiveBad + naiveGood) / N;
  const wrongAll = passedBad + rejGood;
  const pub = d.published, pb = pub?.perBoard, few = d.fewshot;
  const last = (k: string) => pb?.[k]?.[pb[k].length - 1]?.[0];
  return (
    <div className="space-y-4">
      <PageHead title="Scoreboard: right, wrong, and asked"
        sub={`Every held-out test board of ${keys.length === 4 ? 'the four PCBs' : keys.join(', ')} (${N} boards the station never saw) went through the whole station once. These are counts, not estimates. Published results of well-known methods on the same dataset are shown next to ours, with what is and is not comparable.`}
        aside={<Measured />} />

      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <Kpi label="Accuracy as a plain good / defective classifier" value={pct(accAll, 1)} tone={accAll >= 0.9 ? 'var(--pass)' : 'var(--doubt)'}
          sub={`one threshold fixed before the test (5% of good boards rejected), no "ask a person": ${N - naiveBad - naiveGood} of ${N} right. This is the number to compare with other models.`} />
        <Kpi label="Accuracy on the boards it decided alone" value={right + wrongAll ? pct(right / (right + wrongAll), 1) : '–'} tone="var(--pass)"
          sub={`${right} right, ${wrongAll} wrong out of ${right + wrongAll} it did not send to a person`} />
        <Kpi label="Ranking quality (AUROC), mean of the boards" value={(100 * sum(r => r.aurocStation) / rows.length).toFixed(1)}
          sub="how often a defective board scores above a good one; 50 = coin toss, 100 = always" />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Kpi label="Boards tested" value={N} sub={`${sum(r => r.good.total)} good · ${sum(r => r.defective.total)} defective`} />
        <Kpi label="Decided alone, correctly" value={right} sub={pct(right / N, 1)} tone="var(--pass)" />
        <Kpi label="Sent to a person" value={asked} sub={`${pct(asked / N, 1)} · target 10%`} tone="var(--doubt)" />
        <Kpi label="Defective boards passed" value={passedBad} sub={`${pct(passedBad / Math.max(1, sum(r => r.defective.total)), 1)} of defective boards`} tone={passedBad ? 'var(--fail)' : 'var(--pass)'} />
        <Kpi label="Good boards rejected" value={rejGood} sub={`${pct(rejGood / Math.max(1, sum(r => r.good.total)), 1)} of good boards · bound 2%`} tone={rejGood ? 'var(--fail)' : 'var(--pass)'} />
      </div>

      <Panel title="Board by board">
        <div className="overflow-x-auto">
          <table className="w-full text-sm num">
            <thead className="text-left text-xs text-mist">
              <tr>
                <th className="py-1.5">Board</th><th className="w-[22%]">Right alone · asked · wrong</th>
                <th className="text-right">Good: passed</th><th className="text-right">asked</th><th className="text-right">rejected</th>
                <th className="text-right">Defective: rejected</th><th className="text-right">asked</th><th className="text-right">passed</th>
                <th className="text-right">Plain accuracy</th><th className="text-right">Score AUROC</th>
              </tr>
            </thead>
            <tbody>
              {keys.map(k => {
                const r = d.ours[k];
                return (
                  <tr key={k} className="border-t border-line">
                    <td className="py-2"><span className="mono text-[11px] text-mist mr-2">{k}</span>{NAMES[k]}</td>
                    <td><Bar right={r.decidedAloneAndRight} asked={r.sentToPerson} wrong={r.wrong} /></td>
                    <td className="text-right">{r.good.passed}</td><td className="text-right text-mist">{r.good.askedPerson + r.good.held}</td>
                    <td className="text-right" style={{ color: r.good.wronglyRejected ? 'var(--fail)' : undefined, fontWeight: r.good.wronglyRejected ? 700 : 400 }}>{r.good.wronglyRejected}</td>
                    <td className="text-right">{r.defective.rejected}</td><td className="text-right text-mist">{r.defective.askedPerson + r.defective.held}</td>
                    <td className="text-right" style={{ color: r.defective.wronglyPassed ? 'var(--fail)' : undefined, fontWeight: r.defective.wronglyPassed ? 700 : 400 }}>{r.defective.wronglyPassed}</td>
                    <td className="text-right font-semibold" style={{ color: acc(r) >= 0.9 ? 'var(--pass)' : 'var(--doubt)' }}>{pct(acc(r), 1)}</td>
                    <td className="text-right">{f1(r.aurocStation)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-mist mt-3">
          "Asked" boards are not counted as right or wrong: a person decides them. The same scores with one fixed threshold and no "ask a person" band
          (set in advance to reject 5% of good boards) would have passed <b className="text-bone">{naiveBad}</b> defective boards and rejected <b className="text-bone">{naiveGood}</b> good ones,
          against <b className="text-bone">{passedBad}</b> and <b className="text-bone">{rejGood}</b> here. The price is the {asked} boards a person has to look at.
        </p>
      </Panel>

      {pb && (
        <Panel title="Against a published method, board by board (image AUROC, %)">
          <div className="overflow-x-auto">
            <table className="w-full text-sm num">
              <thead className="text-left text-xs text-mist">
                <tr><th className="py-1.5">Method</th><th>Good photos used</th>{keys.map(k => <th key={k} className="text-right">{k}</th>)}</tr>
              </thead>
              <tbody>
                {pb.shots.map((sh: number, i: number) => (
                  <tr key={sh} className="border-t border-line">
                    <td className="py-1.5">AnomalyDINO-S, 672 px <span className="text-mist text-xs">published</span></td><td>{sh}</td>
                    {keys.map(k => <td key={k} className="text-right">{pb[k][i][0].toFixed(1)} <span className="text-mist text-xs">±{pb[k][i][1]}</span></td>)}
                  </tr>
                ))}
                {few && [0, 2, 5].map(i => (
                  <tr key={`f${i}`} className="border-t border-line">
                    <td className="py-1.5">Sandeha, patch memory alone, 448 px <span className="text-mist text-xs">measured here</span></td><td>{few[keys[0]].curve[i].n}</td>
                    {keys.map(k => <td key={k} className="text-right">{f1(few[k].curve[i].auroc)}</td>)}
                  </tr>
                ))}
                <tr className="border-t-2" style={{ borderColor: 'var(--bone)' }}>
                  <td className="py-1.5 font-semibold">Sandeha, whole station <span className="text-mist text-xs font-normal">measured here</span></td><td>30</td>
                  {keys.map(k => <td key={k} className="text-right font-semibold">{f1(d.ours[k].aurocStation)}</td>)}
                </tr>
              </tbody>
            </table>
          </div>
          <ul className="text-sm list-disc pl-5 mt-3 space-y-1.5">
            {keys.map(k => {
              const ours = 100 * d.ours[k].aurocStation, theirs = last(k), diff = ours - theirs;
              return <li key={k}><b>{k}</b>: whole station {ours.toFixed(1)} with 30 photos, published method {theirs.toFixed(1)} with 16. {Math.abs(diff) < 1 ? 'Level.' : diff > 0 ? `Ours is ${diff.toFixed(1)} points higher, with nearly twice the photos.` : `Ours is ${(-diff).toFixed(1)} points lower, even with more photos.`}</li>;
            })}
          </ul>
        </Panel>
      )}

      <div className="grid xl:grid-cols-[1.2fr_1fr] gap-4">
        {pub?.allProducts && (
          <Panel title="Well-known methods on the whole dataset (context)">
            <table className="w-full text-sm num">
              <thead className="text-left text-xs text-mist"><tr><th className="py-1.5">Method</th><th>Needs</th>{pub.allProducts.shots.map((s: number) => <th key={s} className="text-right">{s}</th>)}</tr></thead>
              <tbody>
                {pub.allProducts.methods.map((m: any) => (
                  <tr key={m.name} className="border-t border-line">
                    <td className="py-1.5">{m.name}</td><td className="text-mist text-xs">{m.kind}</td>
                    {m.values.map((v: number | null, i: number) => <td key={i} className="text-right">{v == null ? '–' : v.toFixed(1)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-xs text-mist mt-2">
              Image AUROC in %, mean over all 12 VisA products (not only the PCBs), by number of good photos. With every training photo as a reference,
              AnomalyDINO-S reaches {pub.allProducts.fullShot['AnomalyDINO-S (448 px)']} (448 px) and {pub.allProducts.fullShot['AnomalyDINO-S (672 px)']} (672 px).
              Source: <a className="text-accent" href={pub.source.url} target="_blank" rel="noreferrer">{pub.source.title}</a>. We did not re-run these methods; the numbers are theirs.
            </p>
          </Panel>
        )}
        <Panel title="Read this before quoting a number">
          <ul className="text-sm list-disc pl-5 space-y-1.5">
            <li><b>The detector is not our invention.</b> A frozen DINOv2 with a patch memory is the same family as AnomalyDINO. Run alone at 448 px, ours scores below the published 672 px results on every board.</li>
            <li><b>What the whole station adds</b> is scoring the board only (not the mat), a second detector on the aligned golden board, and the decision layer: two calibrated lines and an "ask a person" band.</li>
            <li><b>Not the same protocol.</b> We use 30 good photos and 5 known defects (only to place the fail line); the published rows use 1 to 16 good photos, other random draws, and three runs. Ours is one run with seed 0, so a difference of a point or two means nothing.</li>
            <li><b>Each board was judged on its own.</b> Half of this test set is defective; a real line is a few percent. Run as one mixed stream, the station reads that many defects as "conditions changed" and stops deciding alone: on pcb4 it then sent 74% of boards to a person (still 0 wrong). That is the safe behaviour, but it is not the 8% shown above.</li>
            <li><b>AUROC is not accuracy.</b> It says how well the score ranks defective above good. The counts at the top are what a line actually experiences.</li>
            <li><b>Four board types, about 200 boards each.</b> One dataset, one camera setup. A different board, lighting or camera will change every number here.</li>
          </ul>
        </Panel>
      </div>
    </div>
  );
}
