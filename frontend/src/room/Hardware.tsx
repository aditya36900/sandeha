import React from 'react';
import { api } from '../api';
import { useStore } from '../store';
import { Btn, Panel } from '../ui/bits';
import { Chip, Kpi, PageHead, can, statusTone, usePoll } from './common';

const FAULTS: { key: string; title: string; effect: string }[] = [
  { key: 'camera', title: 'Camera dies', effect: 'frames go black → every part is HELD, nothing is judged blind' },
  { key: 'accelerator', title: 'Accelerator throttles', effect: 'inference slows by 0.6 s → latency alert' },
  { key: 'conveyor', title: 'Conveyor loses tracking', effect: 'parts cannot be routed → HOLD on the belt' },
  { key: 'network', title: 'Network drops', effect: 'messages to the PLC and inspectors queue, then flush on recovery' },
];

const meter = (v: number | null | undefined, max = 100) => (
  <div className="h-1.5 bg-line rounded-full mt-2"><div className="h-full rounded-full" style={{ width: `${Math.min(100, (100 * (v ?? 0)) / max)}%`, background: (v ?? 0) > 0.85 * max ? 'var(--fail)' : (v ?? 0) > 0.6 * max ? 'var(--doubt)' : 'var(--pass)' }} /></div>
);

export default function Hardware() {
  const { role, setError, station } = useStore();
  const [t, reload] = usePoll(api.telemetry, 3000);
  const [out, reloadOut] = usePoll(() => api.outbox(40), 4000);
  const [prof] = usePoll(api.profile, 10000);
  const act = async (fn: () => Promise<unknown>) => { try { await fn(); reload(); reloadOut(); } catch (e: any) { setError(e.message); } };
  const faults = station?.faults ?? t?.faults ?? [];
  const m = t?.measured;
  const gpu = m?.gpu;
  return (
    <div className="space-y-5">
      <PageHead title="Hardware" sub="Measured numbers come from this machine (psutil, nvidia-smi). Camera, conveyor, LED ring and network are simulated devices, clearly labelled, so faults can be rehearsed safely." />
      {prof && (
        <Panel title="Inspection profile" aside={<Chip tone={prof.profile === 'edge' ? 'var(--doubt)' : 'var(--accent)'}>{prof.profile}</Chip>}>
          <div className="grid sm:grid-cols-2 xl:grid-cols-4 gap-3 text-sm">
            <div><div className="label">backbone</div>{prof.backbone}<div className="text-xs text-mist">device {prof.device}</div></div>
            <div><div className="label">detectors</div>{prof.detectors.join(' + ')}<div className="text-xs text-mist">golden gain {prof.goldenGain}</div></div>
            <div><div className="label">memory</div>{Object.values(prof.memory as Record<string, any>).map((x: any) => x.patches.toLocaleString()).join(' / ') || '—'} patches{prof.coreset ? <div className="text-xs text-mist">coreset {Math.round(prof.coreset * 100)}% kept</div> : <div className="text-xs text-mist">full memory</div>}</div>
            <div><div className="label">latency p50</div>{prof.latencyMsP50 ? `${Math.round(prof.latencyMsP50)} ms` : '—'}<div className="text-xs text-mist">VLM {prof.vlm ? 'on' : 'off'} · CLIP {prof.clip ? 'on' : 'off'}</div></div>
          </div>
          <p className="text-xs text-mist mt-2">Small hardware: start with <span className="mono">SANDEHA_PROFILE=edge</span> (INT8 ONNX on CPU threads, 10% coreset memory, no language model). Measured numbers for both profiles are in the README.</p>
        </Panel>
      )}
      {m && (
        <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3">
          <div><Kpi label="CPU" value={`${Math.round(m.cpuPercent)}%`} sub={`${m.cpuCores} cores`} />{meter(m.cpuPercent)}</div>
          <div><Kpi label="RAM" value={`${m.ramUsedGB} GB`} sub={`of ${m.ramTotalGB} GB`} />{meter(m.ramPercent)}</div>
          <div><Kpi label="GPU" value={gpu ? `${Math.round(gpu.utilPercent)}%` : 'none'} sub={gpu ? `${gpu.name}` : 'CPU only'} />{gpu && meter(gpu.utilPercent)}</div>
          <div><Kpi label="GPU memory" value={gpu ? `${(gpu.memUsedMB / 1024).toFixed(1)} GB` : '—'} sub={gpu ? `of ${(gpu.memTotalMB / 1024).toFixed(1)} GB · ${gpu.tempC}°C` : undefined} />{gpu && meter(gpu.memUsedMB, gpu.memTotalMB)}</div>
          <Kpi label="Inference p50" value={m.inferenceMsP50 ? `${Math.round(m.inferenceMsP50)} ms` : '—'} sub={m.partsPerSecond ? `${m.partsPerSecond} parts/s (goal ≥ 5)` : 'no parts yet'} tone={m.partsPerSecond && m.partsPerSecond >= 5 ? 'var(--pass)' : undefined} />
          <Kpi label="Parts inspected" value={m.partsInspected.toLocaleString()} sub={`${m.productLines} product lines`} />
          <Kpi label="Uptime" value={`${Math.round(m.uptimeMin)} min`} />
          <Kpi label="Disk free" value={`${m.diskFreeGB} GB`} sub={`saved lines ${m.savedSessionsMB} MB`} />
        </div>
      )}
      <div className="grid xl:grid-cols-2 gap-5">
        <Panel title="Devices (simulated)">
          <ul className="grid sm:grid-cols-2 gap-3">
            {t && Object.entries(t.simulated).map(([k, d]) => (
              <li key={k} className="bg-raised rounded-xl p-3">
                <div className="flex justify-between items-center"><span className="font-semibold capitalize">{k.replace(/([A-Z])/g, ' $1')}</span><Chip tone={statusTone(d.status)}>{d.status}</Chip></div>
                <div className="text-xs text-mist mt-1">{Object.entries(d).filter(([x]) => x !== 'status').map(([x, v]) => `${x}: ${Array.isArray(v) ? v.join(', ') : v}`).join(' · ')}</div>
              </li>
            ))}
          </ul>
        </Panel>
        <Panel title="Rehearse a failure" aside={<Btn tone="pass" disabled={!faults.length || !can(role, 'INSPECTOR', 'QUALITY_MANAGER', 'ADMIN')} onClick={() => act(api.restore)}
          title={can(role, 'INSPECTOR', 'QUALITY_MANAGER', 'ADMIN') ? undefined : 'An inspector or above must restore'}>Restore all</Btn>}>
          <ul className="space-y-2">
            {FAULTS.map(f => {
              const on = faults.includes(f.key);
              return (
                <li key={f.key} className="flex items-center gap-3 bg-raised rounded-xl p-3">
                  <div className="flex-1 min-w-0"><div className="font-semibold">{f.title} {on && <Chip tone="var(--fail)">ACTIVE</Chip>}</div><div className="text-xs text-mist">{f.effect}</div></div>
                  <Btn tone={on ? 'ghost' : 'fail'} disabled={on} onClick={() => act(() => api.fault(f.key))}>{on ? 'Injected' : 'Inject'}</Btn>
                </li>
              );
            })}
          </ul>
          <p className="text-xs text-mist mt-2">Then scan parts on the line: the verdicts become HOLD with the reason, and an alert is raised.</p>
        </Panel>
      </div>
      <Panel title="Messages to the line and inspectors" aside={<span className="text-xs text-mist">Zenoh topic to the PLC · Telegram to inspectors · simulated without a broker</span>}>
        <div className="overflow-x-auto max-h-80">
          <table className="w-full text-sm num">
            <thead className="text-mist text-xs text-left sticky top-0 bg-surface"><tr><th className="py-1">Time</th><th>Channel</th><th>Status</th><th>Payload</th></tr></thead>
            <tbody>
              {(out ?? []).map((o, i) => (
                <tr key={i} className="border-t border-line">
                  <td className="py-1 text-mist">{o.t.slice(11)}</td><td>{o.channel}</td><td><Chip tone={statusTone(o.status)}>{o.status}</Chip></td>
                  <td className="text-xs max-w-[520px] truncate" title={JSON.stringify(o.payload)}>{o.payload.text ?? `${o.payload.topic ?? ''} ${o.payload.decision ?? ''} ${o.payload.routing ?? ''}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!out?.length && <p className="text-mist text-sm mt-2">No messages since the station started. Every decision publishes one to the line PLC; every doubt pings an inspector.</p>}
        </div>
      </Panel>
    </div>
  );
}
