import React, { useEffect, useState } from 'react';
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../api';
import { useStore } from '../store';
import { Btn, Panel, Voice, decisionColor } from '../ui/bits';

const SLIDERS: { key: string; label: string; min: number; max: number; step: number; base: number }[] = [
  { key: 'brightness', label: 'Light level', min: 0.4, max: 1.6, step: 0.05, base: 1 },
  { key: 'color_temp', label: 'Colour of light', min: -1, max: 1, step: 0.1, base: 0 },
  { key: 'falloff', label: 'Light from one side', min: 0, max: 1, step: 0.05, base: 0 },
  { key: 'rotation', label: 'Camera rotated (°)', min: -15, max: 15, step: 1, base: 0 },
  { key: 'perspective', label: 'Camera tilted', min: 0, max: 1, step: 0.05, base: 0 },
  { key: 'contrast', label: 'Surface finish contrast', min: 0.5, max: 1.5, step: 0.05, base: 1 },
  { key: 'sheen', label: 'Glare / sheen', min: 0, max: 1, step: 0.05, base: 0 },
  { key: 'blur', label: 'Blur / dirty lens', min: 0, max: 4, step: 0.2, base: 0 },
  { key: 'noise', label: 'Sensor noise', min: 0, max: 0.1, step: 0.005, base: 0 }
];

const PRESET_NAMES: Record<string, string> = {
  night_shift_lights: 'Night-shift lights',
  skylight_glare: 'Sunlight through the skylight',
  camera_bumped: 'Someone bumped the camera',
  new_surface_finish: 'New supplier, new surface finish',
  dirty_lens: 'Dirty lens'
};

export default function Chaos() {
  const { view, sessionId, setError } = useStore();
  const [c, setC] = useState<Record<string, number>>(Object.fromEntries(SLIDERS.map(s => [s.key, s.base])));
  const [presets, setPresets] = useState<Record<string, Record<string, number>>>({});
  const [msg, setMsg] = useState('');
  const [prev, setPrev] = useState<{ before: string; after: string } | null>(null);
  useEffect(() => { api.presets().then(setPresets).catch(() => {}); }, []);
  // live preview of what the camera sees, debounced while sliders move
  useEffect(() => {
    if (!sessionId) return;
    const t = setTimeout(() => { api.preview(sessionId, c).then(setPrev).catch(() => {}); }, 180);
    return () => clearTimeout(t);
  }, [sessionId, c]);
  if (!view || !sessionId) return null;

  const apply = async (next: Record<string, number>) => {
    setC(next);
    try { await api.conditions(sessionId, next); } catch (e: any) { setError(e.message); }
  };
  const run = (n: number, rate = 0.1) => api.stream(sessionId, n, rate, 0.12).catch((e: any) => setError(e.message));
  const adapt = async () => {
    try { setMsg((await api.adapt(sessionId, 5)).message); } catch (e: any) { setError(e.message); }
  };
  const forgettingCheck = async () => {
    await apply(Object.fromEntries(SLIDERS.map(s => [s.key, s.base])));
    setMsg('Back to the original conditions: running parts to check nothing was forgotten.');
    await run(15, 0.2);
  };

  const recent = view.records.slice(-90);
  const data = recent.map((r, i) => ({ i, m: Math.max(r.martingale, 0.01), d: r.decision }));

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[380px_minmax(0,1fr)] gap-5">
      <Panel title="Break the line">
        <p className="text-mist text-sm mb-4">The organisers will change lighting, camera angle or surface finish mid-run. Do it here first.</p>
        <div className="flex flex-wrap gap-2 mb-5">
          {Object.entries(presets).map(([k, v]) => (
            <Btn key={k} tone="ghost" onClick={() => apply({ ...Object.fromEntries(SLIDERS.map(s => [s.key, s.base])), ...v })}>{PRESET_NAMES[k] ?? k}</Btn>
          ))}
        </div>
        <div className="space-y-3">
          {SLIDERS.map(s => (
            <label key={s.key} className="block text-sm">
              <div className="flex justify-between"><span>{s.label}</span><span className="num text-mist">{c[s.key]}</span></div>
              <input className="w-full" type="range" min={s.min} max={s.max} step={s.step} value={c[s.key]}
                onChange={e => setC({ ...c, [s.key]: +e.target.value })} onMouseUp={() => apply(c)} onKeyUp={() => apply(c)} onTouchEnd={() => apply(c)} />
            </label>
          ))}
        </div>
        <div className="flex gap-2 mt-5">
          <Btn tone="ghost" onClick={() => apply(Object.fromEntries(SLIDERS.map(s => [s.key, s.base])))}>Restore original</Btn>
        </div>
      </Panel>

      <div className="space-y-5">
        {prev && (
          <Panel title="What the camera sees">
            <div className="grid grid-cols-2 gap-3">
              <figure><img src={prev.before} alt="Reference conditions" className="rounded-xl w-full" /><figcaption className="text-xs text-mist mt-1">Conditions I learned</figcaption></figure>
              <figure><img src={prev.after} alt="Current conditions" className="rounded-xl w-full" /><figcaption className="text-xs text-mist mt-1">Conditions right now</figcaption></figure>
            </div>
          </Panel>
        )}
        <Panel title="Evidence that something changed" aside={<span className="text-mist text-sm">alarm at 200: quiet on normal production in our tests</span>}>
          <div className="h-64">
            <ResponsiveContainer>
              <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
                <CartesianGrid stroke="var(--line)" strokeDasharray="2 4" />
                <XAxis dataKey="i" tick={{ fill: 'var(--mist)', fontSize: 12 }} />
                <YAxis scale="log" domain={[0.01, 'auto']} allowDataOverflow tick={{ fill: 'var(--mist)', fontSize: 12 }} />
                <Tooltip contentStyle={{ background: 'var(--surface)', border: 'none', borderRadius: 12 }} />
                <ReferenceLine y={200} stroke="var(--doubt)" strokeDasharray="6 4" label={{ value: 'alarm', fill: 'var(--doubt)', fontSize: 12 }} />
                <Line type="monotone" dataKey="m" stroke="var(--bone)" dot={false} strokeWidth={2} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="flex gap-1 flex-wrap mt-2">
            {recent.map(r => <span key={r.id} className="w-2.5 h-2.5 rounded-sm" style={{ background: decisionColor[r.decision] }} />)}
          </div>
        </Panel>

        <Panel>
          {view.alarm ? (
            <Voice className="text-doubt">The line no longer looks like my references. I've stopped approving parts on my own. Show me five good parts under the new conditions and I'll adapt without retraining.</Voice>
          ) : (
            <Voice>Conditions look like my references. Change something and run parts: I'll notice.</Voice>
          )}
          {msg && <p className="text-pass mt-3">{msg}</p>}
          <div className="flex flex-wrap gap-2 mt-4">
            <Btn tone="doubt" onClick={() => run(25)}>Run 25 parts</Btn>
            <Btn tone={view.alarm ? 'pass' : 'ghost'} onClick={adapt}>Teach me the new conditions (5 photos)</Btn>
            <Btn tone="ghost" onClick={forgettingCheck}>Check I didn't forget the old conditions</Btn>
          </div>
        </Panel>
      </div>
    </div>
  );
}
