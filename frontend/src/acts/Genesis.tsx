import React, { Suspense, lazy } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useStore } from '../store';
import { Btn, Panel, Voice } from '../ui/bits';

const Twin3D = lazy(() => import('../ui/Twin3D'));
const Lightbox3D = lazy(() => import('../ui/Lightbox3D'));

function Steps() {
  const { view } = useStore();
  if (!view) return null;
  const steps: [string, boolean][] = [
    ['Photos received', view.photos.length > 0],
    [view.summary?.relief || (view.cloud && view.cloud.cameras.length === 0) ? '3D relief from one photo' : '3D twin carved',
      !!view.cloud && (view.cloud.step ?? 1) >= (view.cloud.total ?? 0)] as [string, boolean],
    ['Patch memory learned', !!view.patches || view.imagined.length > 0],
    ['Defects imagined', view.imagined.length > 0],
    ['Doubt calibrated', !!view.policy],
    ['Questions ready', view.questions.length > 0]
  ];
  const next = steps.findIndex(s => !s[1]);
  return (
    <ol className="space-y-2">
      {steps.map(([label, done], i) => (
        <li key={label} className="flex items-center gap-3 text-sm">
          <span className={`w-5 h-5 rounded-full grid place-items-center text-[11px] font-semibold ${done ? 'bg-pass text-ink' : i === next ? 'border-2 border-doubt text-doubt' : 'border border-line text-mist'}`}>
            {done ? '✓' : i + 1}
          </span>
          <span className={done ? 'text-bone' : i === next ? 'text-doubt' : 'text-mist'}>{label}{i === next ? '…' : ''}</span>
        </li>
      ))}
    </ol>
  );
}

export default function Genesis() {
  const { view, setAct } = useStore();
  if (!view) return null;
  const last = view.narration[view.narration.length - 1];
  const carving = view.cloud && view.cloud.step !== undefined && view.cloud.step < (view.cloud.total ?? 0);
  const ready = view.stage === 'INTERVIEW' || view.stage === 'LINE';

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_380px] gap-5">
      <div className="space-y-5 min-w-0">
        <Panel>
          <div className="relative">
            <Suspense fallback={<div className="h-[440px] grid place-items-center text-mist">Preparing the viewer…</div>}>
              {view.cloud ? (
                <Twin3D cloud={view.cloud} height={440} />
              ) : view.photos.length ? (
                <Lightbox3D photos={view.photos} height={440} />
              ) : (
                <div className="h-[440px] grid place-items-center text-mist">Waiting for the first photos…</div>
              )}
            </Suspense>
            <div className="absolute left-4 bottom-4 right-4 pointer-events-none">
              <AnimatePresence mode="wait">
                {last && (
                  <motion.div key={last.t} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
                    <Voice className="text-[26px] drop-shadow">{last.text}</Voice>
                  </motion.div>
                )}
              </AnimatePresence>
              {view.cloud && (
                <div className="text-mist text-sm num mt-1">
                  {carving ? `View ${view.cloud.step} of ${view.cloud.total}`
                    : view.cloud.cameras.length === 0 ? `${view.cloud.count.toLocaleString()}-point relief estimated from one photo`
                    : `${view.cloud.count.toLocaleString()} surface points carved from ${view.cloud.cameras.length} photos`}
                </div>
              )}
            </div>
          </div>
        </Panel>

        {view.imagined.length > 0 && (
          <Panel title="Defects I imagined before seeing any" aside={<span className="text-mist text-sm">to test myself and set my doubt</span>}>
            <div className="grid grid-cols-4 sm:grid-cols-7 gap-2">
              {view.imagined.map((g, i) => (
                <figure key={i} className="text-center">
                  <img src={g.thumb} alt={`Imagined ${g.kind}`} className="rounded-lg w-full aspect-square object-cover" />
                  <figcaption className="text-xs text-mist mt-1">{g.kind} · {g.sizePct}%</figcaption>
                </figure>
              ))}
            </div>
          </Panel>
        )}
      </div>

      <div className="space-y-5">
        <Panel title="Learning this product"><Steps /></Panel>
        <Panel title="Reference photos" aside={<span className="text-mist text-sm num">{view.photos.length}</span>}>
          <div className="grid grid-cols-6 gap-1.5">
            {view.photos.map((p, i) => (
              <motion.img key={i} src={p} alt="" className="rounded-md aspect-square object-cover"
                initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: i * 0.02 }} />
            ))}
          </div>
        </Panel>
        <Panel title="What I'm doing">
          <ol className="space-y-2 max-h-[300px] overflow-auto pr-1">
            {view.narration.map((n, i) => (
              <li key={i} className="voice text-lg leading-snug" style={{ color: n.tone === 'doubt' ? 'var(--doubt)' : n.tone === 'pass' ? 'var(--pass)' : undefined }}>
                {n.text}
              </li>
            ))}
          </ol>
        </Panel>
        {view.policy && (
          <Panel title="My first calibration">
            <p className="text-sm text-mist">Below the pass line I approve automatically, above the fail line I reject, and in between I ask a person.</p>
            <div className="mt-3 flex gap-6 num">
              <div><div className="text-pass text-2xl font-semibold">{view.policy.tau_pass.toFixed(3)}</div><div className="text-mist text-sm">pass line</div></div>
              <div><div className="text-fail text-2xl font-semibold">{view.policy.tau_fail.toFixed(3)}</div><div className="text-mist text-sm">fail line</div></div>
            </div>
          </Panel>
        )}
        <Btn tone="doubt" disabled={!ready} onClick={() => setAct('interview')}>
          {ready ? 'Hear my questions' : 'Still learning…'}
        </Btn>
      </div>
    </div>
  );
}
