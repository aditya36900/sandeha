import React, { useEffect, useRef, useState } from 'react';
import { api, InspectionRecord } from '../api';
import { Btn } from './bits';

/** Live camera scanning from the browser: laptop webcam or a phone. Holds the frame until the board is steady,
 *  then captures and sends it to the station like any other board. */
export default function CameraScan({ sessionId, onResult, onError }: { sessionId: string; onResult: (r: InspectionRecord) => void; onError: (m: string) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [on, setOn] = useState(false);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [device, setDevice] = useState<string>('');
  const [auto, setAuto] = useState(true);
  const [steady, setSteady] = useState(0);      // 0..1, how still the scene is
  const [busy, setBusy] = useState(false);
  const [count, setCount] = useState(0);
  const last = useRef<Uint8ClampedArray | null>(null);
  const steadyFrames = useRef(0);
  const cooldown = useRef(0);
  const stream = useRef<MediaStream | null>(null);

  const stop = () => { stream.current?.getTracks().forEach(t => t.stop()); stream.current = null; setOn(false); };
  const start = async () => {
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: { deviceId: device ? { exact: device } : undefined, width: { ideal: 1280 }, height: { ideal: 960 }, facingMode: 'environment' } });
      stream.current = s;
      if (video.current) { video.current.srcObject = s; await video.current.play(); }
      setOn(true);
      const list = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === 'videoinput');
      setDevices(list);
    } catch (e: any) { onError(`Camera: ${e.message}. Allow camera access in the browser, or plug a camera in.`); }
  };
  useEffect(() => () => stop(), []);

  const capture = async () => {
    const v = video.current, c = canvas.current;
    if (!v || !c || busy) return;
    const side = Math.min(v.videoWidth, v.videoHeight);
    c.width = c.height = 1024;
    const ctx = c.getContext('2d')!;
    ctx.drawImage(v, (v.videoWidth - side) / 2, (v.videoHeight - side) / 2, side, side, 0, 0, 1024, 1024);
    setBusy(true);
    try {
      const blob: Blob = await new Promise(res => c.toBlob(b => res(b!), 'image/jpeg', 0.92));
      const r = await api.inspect(sessionId, new File([blob], `camera-${Date.now()}.jpg`, { type: 'image/jpeg' }));
      setCount(n => n + 1);
      onResult(r);
      cooldown.current = Date.now() + 4000;
    } catch (e: any) { onError(e.message); } finally { setBusy(false); }
  };

  // steadiness: mean absolute difference between consecutive small frames
  useEffect(() => {
    if (!on) return;
    const v = video.current!;
    const small = document.createElement('canvas'); small.width = small.height = 64;
    const sctx = small.getContext('2d', { willReadFrequently: true })!;
    const t = setInterval(() => {
      if (!v.videoWidth) return;
      const side = Math.min(v.videoWidth, v.videoHeight);
      sctx.drawImage(v, (v.videoWidth - side) / 2, (v.videoHeight - side) / 2, side, side, 0, 0, 64, 64);
      const d = sctx.getImageData(0, 0, 64, 64).data;
      if (last.current) {
        let sum = 0;
        for (let i = 0; i < d.length; i += 4) sum += Math.abs(d[i] - last.current[i]) + Math.abs(d[i + 1] - last.current[i + 1]);
        const motion = sum / (d.length / 2) / 255;  // 0 still .. 1 chaos
        const s = Math.max(0, 1 - motion * 12);
        setSteady(s);
        steadyFrames.current = s > 0.85 ? steadyFrames.current + 1 : 0;
        if (auto && steadyFrames.current >= 6 && !busy && Date.now() > cooldown.current) { steadyFrames.current = 0; capture(); }
      }
      last.current = new Uint8ClampedArray(d);
    }, 150);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [on, auto, busy]);

  return (
    <div className="grid lg:grid-cols-[minmax(0,1fr)_260px] gap-4">
      <div className={`relative aspect-square rounded-xl overflow-hidden bg-ink corner ${on ? 'scanlines' : ''}`}>
        <video ref={video} playsInline muted className={`absolute inset-0 w-full h-full object-cover ${on ? '' : 'hidden'}`} />
        <canvas ref={canvas} className="hidden" />
        {!on && (
          <div className="absolute inset-0 grid place-items-center text-center p-6">
            <div>
              <div className="display text-2xl font-semibold">Point a camera at a board</div>
              <p className="text-mist text-sm mt-2 max-w-sm">Laptop webcam or phone. Hold the board steady in the square; it captures by itself and scans like any other board. Same product, similar framing as the good photos.</p>
              <div className="mt-4"><Btn tone="accent" onClick={start}>Start camera</Btn></div>
            </div>
          </div>
        )}
        {on && (
          <>
            {busy && <div className="sweep" />}
            <div className="absolute left-3 bottom-3 right-3 flex items-center gap-3">
              <div className="flex-1 h-1.5 rounded-full bg-ink/70 overflow-hidden"><div className="h-full transition-all" style={{ width: `${steady * 100}%`, background: steady > 0.85 ? 'var(--pass)' : 'var(--doubt)' }} /></div>
              <span className="label !text-bone">{busy ? 'scanning' : steady > 0.85 ? 'steady' : 'hold still'}</span>
            </div>
            <div className="absolute top-3 right-3 flex items-center gap-2"><span className="w-2 h-2 rounded-full bg-fail pulse-ring text-fail relative" /><span className="label !text-bone">live</span></div>
          </>
        )}
      </div>
      <div className="space-y-3 text-sm">
        <div className="label">Camera</div>
        {devices.length > 1 && (
          <select value={device} onChange={e => { setDevice(e.target.value); stop(); setTimeout(start, 100); }} className="w-full bg-raised rounded-lg px-2 py-1.5 border border-line" aria-label="Camera">
            {devices.map(d => <option key={d.deviceId} value={d.deviceId}>{d.label || 'camera'}</option>)}
          </select>
        )}
        <label className="flex items-center gap-2"><input type="checkbox" checked={auto} onChange={e => setAuto(e.target.checked)} /> capture automatically when steady</label>
        <div className="flex gap-2 flex-wrap">
          <Btn tone="accent" disabled={!on || busy} onClick={capture}>{busy ? 'Scanning…' : 'Scan now'}</Btn>
          {on ? <Btn tone="ghost" onClick={stop}>Stop</Btn> : null}
        </div>
        <div className="text-mist text-xs">{count ? `${count} board${count === 1 ? '' : 's'} scanned from the camera this session.` : 'Each capture is cropped square and sent at 1024 px. The phone route: open this page on the phone on the same Wi-Fi.'}</div>
        <div className="text-mist text-xs">Camera frames never leave this machine except to the station on localhost.</div>
      </div>
    </div>
  );
}
