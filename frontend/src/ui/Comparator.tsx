import React, { useEffect, useRef, useState } from 'react';
import { InspectionRecord } from '../api';

/** Blink comparator: wipe between the golden board, this board and the deviation map, the way an inspector
 *  flicks between a reference and a part under a loupe. */
export default function Comparator({ rec, goldenUrl }: { rec: InspectionRecord; goldenUrl: string | null }) {
  const [x, setX] = useState(0.5);
  const [layer, setLayer] = useState<'board' | 'diff' | 'heat'>('diff');
  const [blink, setBlink] = useState(false);
  const [show, setShow] = useState<'golden' | 'this'>('this');
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!blink) return;
    const t = setInterval(() => setShow(s => (s === 'golden' ? 'this' : 'golden')), 450);
    return () => clearInterval(t);
  }, [blink]);
  const aligned = rec.board?.aligned ?? rec.image_url;
  const top = layer === 'diff' ? rec.diff_url ?? aligned : layer === 'heat' ? rec.heat_url : aligned;
  const drag = (e: React.PointerEvent) => {
    if (!box.current || e.buttons === 0) return;
    const r = box.current.getBoundingClientRect();
    setX(Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)));
  };
  if (!goldenUrl) return null;
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <span className="label">Golden vs this board</span>
        <div className="flex gap-1 text-[11px] ml-auto">
          {(['diff', 'board', 'heat'] as const).map(l => (
            <button key={l} onClick={() => setLayer(l)} className={`px-2 py-1 rounded-md ${layer === l ? 'bg-raised text-bone' : 'text-mist hover:text-bone'}`}>
              {l === 'diff' ? 'deviation' : l === 'board' ? 'photo' : 'patch heat'}
            </button>
          ))}
          <button onClick={() => setBlink(b => !b)} className={`px-2 py-1 rounded-md ${blink ? 'bg-accent text-ink font-semibold' : 'text-mist hover:text-bone'}`}>{blink ? 'blinking' : 'blink'}</button>
        </div>
      </div>
      <div ref={box} onPointerDown={drag} onPointerMove={drag} className="relative w-full rounded-xl overflow-hidden bg-ink select-none cursor-ew-resize touch-none" style={{ aspectRatio: '3 / 2' }}>
        <img src={goldenUrl} alt="Golden board" className="absolute inset-0 w-full h-full object-contain" draggable={false} />
        {!blink && (
          <>
            <div className="absolute inset-0" style={{ clipPath: `inset(0 0 0 ${x * 100}%)` }}>
              <img src={top ?? aligned} alt="This board" className="absolute inset-0 w-full h-full object-contain" draggable={false} />
            </div>
            <div className="absolute top-0 bottom-0 w-0.5 bg-accent" style={{ left: `${x * 100}%`, boxShadow: '0 0 12px var(--accent)' }}>
              <span className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-7 h-7 rounded-full bg-accent text-ink grid place-items-center text-xs font-bold">⇔</span>
            </div>
            <span className="absolute left-2 top-2 label !text-bone bg-ink/70 px-1.5 rounded">golden</span>
            <span className="absolute right-2 top-2 label !text-bone bg-ink/70 px-1.5 rounded">{layer === 'diff' ? 'deviation' : layer === 'heat' ? 'patch heat' : 'this board'}</span>
          </>
        )}
        {blink && show === 'this' && <img src={top ?? aligned} alt="This board" className="absolute inset-0 w-full h-full object-contain" draggable={false} />}
        {blink && <span className="absolute left-2 top-2 label !text-bone bg-ink/70 px-1.5 rounded">{show}</span>}
      </div>
      <p className="text-xs text-mist mt-1.5">Drag the line. The deviation layer paints how many "spreads" each pixel sits from the 30 good boards (the second detector); orange is beyond anything normal.</p>
    </div>
  );
}
