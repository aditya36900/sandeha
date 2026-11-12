import React, { Suspense, lazy, useState } from 'react';
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api, Galaxy, Summary } from '../api';
import { useStore, useInterval } from '../store';
import { Btn, Panel, Voice } from '../ui/bits';

const Galaxy3D = lazy(() => import('../ui/Galaxy3D'));

function Forecast() {
  const { sessionId, setError } = useStore();
  const [s, setS] = useState<Summary | null>(null);
  useInterval(() => { if (sessionId) api.session(sessionId).then(setS).catch(() => {}); }, 1500, [sessionId]);
  const f = s?.forecast;
  const data = (f?.ewma ?? []).map((v, i) => ({ i, v }));
  const statusText = f?.status === 'STORM_COMING'
    ? (f.partsUntilStorm === 0
      ? 'The storm is here: parts are now crossing my pass line. Stop and check the tool before defects pile up.'
      : `A defect storm is coming: weak anomalies are rising and will cross my pass line in about ${f.partsUntilStorm} parts.`)
    : f?.status === 'DRIFTING' ? 'Passing parts are slowly getting less typical. Something in the process is drifting.'
    : 'Clear: passing parts look as typical as my references.';
  return (
    <Panel title="Defect weather forecast">
      <Voice>{f?.ready ? statusText : 'I watch the parts I pass, not just the ones I reject. Start a production run to see the forecast.'}</Voice>
      {f?.hotspot && <p className="text-doubt mt-2">{f.hotspot.message}</p>}
      <div className="h-56 mt-3">
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" />
            <XAxis dataKey="i" tick={{ fill: 'var(--mist)', fontSize: 12 }} />
            <YAxis tick={{ fill: 'var(--mist)', fontSize: 12 }} domain={['auto', 'auto']} />
            <Tooltip contentStyle={{ background: 'var(--surface)', border: 'none', borderRadius: 12 }} />
            {f?.tauPass && <ReferenceLine y={f.tauPass} stroke="var(--doubt)" strokeDasharray="6 4" label={{ value: 'pass line', fill: 'var(--doubt)', fontSize: 12 }} />}
            <Line dataKey="v" stroke="var(--bone)" dot={false} strokeWidth={2} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-3 flex gap-2">
        <Btn tone="doubt" onClick={() => sessionId && api.wear(sessionId, 60).catch((e: any) => setError(e.message))}>Simulate a wearing cutting tool</Btn>
      </div>
      <p className="text-mist text-xs mt-2">The simulation grows a micro-scratch on each successive good part, the way a worn tool would.</p>
    </Panel>
  );
}

function Hive() {
  const { sessionId, views, start, setError } = useStore();
  const [plantB, setPlantB] = useState<string | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const a = sessionId ? views[sessionId] : null;
  const product = a?.summary ?? null;
  const b = plantB ? views[plantB] : null;
  const learned = product?.learnedDefects ?? [];

  const openB = async () => {
    if (!product) return;
    try {
      const id = await start(product.source, product.name, 'Plant B (Pune)', 7, false);
      setPlantB(id);
      setLog(l => [...l, `Plant B started learning ${product.name} from its own 30 photos.`]);
    } catch (e: any) { setError(e.message); }
  };
  const share = async () => {
    if (!sessionId || !plantB) return;
    try {
      const r = await api.hiveShare(sessionId, plantB);
      setLog(l => [...l, `Shared ${r.shared} defect fingerprint(s): ${r.labels.join(', ')}. ${r.bytesPerFingerprint.toLocaleString()} bytes each, zero pixels.`]);
    } catch (e: any) { setError(e.message); }
  };
  const runB = () => plantB && api.stream(plantB, 15, 0.5, 0.2).then(() => setLog(l => [...l, 'Plant B is inspecting 15 parts.'])).catch((e: any) => setError(e.message));
  const recognised = (b?.records ?? []).filter(r => r.hive_match).length;

  return (
    <Panel title="The hive: one plant's lesson protects another">
      <Voice>When a defect is confirmed at one plant, every plant making the same product can catch it. Only a 384-number fingerprint travels; no image ever leaves the factory.</Voice>
      <ol className="mt-4 space-y-3 text-sm">
        <li>Plant A has learned <span className="font-semibold">{learned.length}</span> confirmed defect fingerprint(s){learned.length ? `: ${learned.join(', ')}` : '. Confirm a defect twice in the review queue first.'}</li>
        <li className="flex items-center gap-3">
          <Btn tone="ghost" disabled={!!plantB || !product} onClick={openB}>Open Plant B</Btn>
          {b && <span className="text-mist">{b.stage === 'INTERVIEW' || b.stage === 'LINE' ? 'Plant B is ready' : 'Plant B is learning…'}</span>}
        </li>
        <li className="flex items-center gap-3">
          <Btn tone="doubt" disabled={!plantB || !learned.length} onClick={share}>Share fingerprints with Plant B</Btn>
          <Btn tone="ghost" disabled={!plantB} onClick={runB}>Run defect-heavy parts at Plant B</Btn>
        </li>
      </ol>
      {b && <p className="mt-3 text-sm num">Plant B recognised <span className="text-pass font-semibold">{recognised}</span> part(s) from Plant A's lessons.</p>}
      <ul className="mt-3 space-y-1 text-mist text-sm">{log.map((x, i) => <li key={i}>{x}</li>)}</ul>
    </Panel>
  );
}

function MemoryGalaxy() {
  const [g, setG] = useState<Galaxy | null>(null);
  const [busy, setBusy] = useState(false);
  const load = async () => { setBusy(true); try { setG(await api.galaxy()); } finally { setBusy(false); } };
  return (
    <Panel title="Everything I remember" aside={<Btn tone="ghost" onClick={load} disabled={busy}>{busy ? 'Mapping…' : g ? 'Refresh map' : 'Map my memory'}</Btn>}>
      {g ? (
        <>
          <Suspense fallback={null}><Galaxy3D g={g} /></Suspense>
          <p className="text-mist text-sm">Soft dots are reference parts; each product forms its own constellation. Diamonds are inspected parts, coloured by my decision. Parts that land in empty space are the ones I doubted.</p>
        </>
      ) : <Voice>Each product I learn becomes a constellation. Inspect some parts, then map my memory.</Voice>}
    </Panel>
  );
}

export default function Beyond() {
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        <Forecast />
        <Hive />
      </div>
      <MemoryGalaxy />
    </div>
  );
}
