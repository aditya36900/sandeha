import React, { useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { api, Question } from '../api';
import { useStore } from '../store';
import { Btn, Panel, Voice } from '../ui/bits';

function ZonePainter({ image, onSave }: { image: string; onSave: (pts: { x: number; y: number; r: number; strictness: number }[]) => void }) {
  const [pts, setPts] = useState<{ x: number; y: number; r: number; strictness: number }[]>([]);
  const ref = useRef<HTMLDivElement>(null);
  const add = (e: React.MouseEvent) => {
    const b = ref.current!.getBoundingClientRect();
    setPts(p => [...p, { x: (e.clientX - b.left) / b.width, y: (e.clientY - b.top) / b.height, r: 0.08, strictness: 1.6 }]);
  };
  return (
    <div>
      <div ref={ref} onClick={add} className="relative cursor-crosshair rounded-xl overflow-hidden w-full max-w-sm aspect-square">
        <img src={image} alt="Paint critical zones" className="w-full h-full object-cover" />
        {pts.map((p, i) => (
          <span key={i} className="absolute rounded-full border-2 border-doubt bg-doubt/25"
            style={{ left: `${(p.x - p.r) * 100}%`, top: `${(p.y - p.r) * 100}%`, width: `${p.r * 200}%`, height: `${p.r * 200}%` }} />
        ))}
      </div>
      <div className="flex gap-2 mt-3">
        <Btn tone="doubt" disabled={!pts.length} onClick={() => onSave(pts)}>Save {pts.length || ''} zones</Btn>
        <Btn tone="ghost" onClick={() => setPts([])}>Clear</Btn>
      </div>
    </div>
  );
}

export default function Interview() {
  const { view, sessionId, setAct, setError } = useStore();
  const [busy, setBusy] = useState<string | null>(null);
  if (!view || !sessionId) return null;
  const qs = view.questions;
  const refImage = view.photos[0];

  const answer = async (q: Question, option: string) => {
    setBusy(q.id);
    try {
      await api.answer(sessionId, q.id, option);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const saveZones = async (q: Question, pts: { x: number; y: number; r: number; strictness: number }[]) => {
    setBusy(q.id);
    try {
      await api.zones(sessionId, pts);
      await api.answer(sessionId, q.id, 'Paint zones');
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const done = qs.length > 0 && qs.every(q => q.answered || q.effect);

  return (
    <div className="max-w-4xl space-y-5">
      <Voice className="text-4xl">Before I inspect a single part, I have {qs.length} questions.</Voice>
      <p className="text-mist">Each question comes from something I noticed in your photos. Your answers change how strict I am and where.</p>
      {qs.map((q, i) => (
        <motion.div key={q.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.08 }}>
          <Panel>
            <div className="grid md:grid-cols-[1fr_220px] gap-5 items-start">
              <div>
                <Voice>{q.question}</Voice>
                <p className="text-mist text-sm mt-2">{q.why}</p>
                {q.type === 'CRITICAL_ZONES' && refImage && !q.effect ? (
                  <div className="mt-4"><ZonePainter image={refImage} onSave={pts => saveZones(q, pts)} /></div>
                ) : (
                  <div className="flex flex-wrap gap-2 mt-4">
                    {q.options.map(o => (
                      <Btn key={o} tone={o === q.options[0] ? 'doubt' : 'ghost'} disabled={!!q.effect || busy === q.id} onClick={() => answer(q, o)}>{o}</Btn>
                    ))}
                  </div>
                )}
                {q.effect && <p className="text-pass mt-3 text-sm">{q.effect}</p>}
              </div>
              <div className="space-y-2">
                {q.image && <img src={q.image} alt="" className="rounded-xl w-full" />}
                {q.crops && (
                  <div className="grid grid-cols-3 gap-1">{q.crops.map((c, k) => <img key={k} src={c} alt="" className="rounded-md" />)}</div>
                )}
              </div>
            </div>
          </Panel>
        </motion.div>
      ))}
      <Btn tone={done ? 'doubt' : 'ghost'} onClick={() => setAct('line')}>{done ? 'Start the line' : 'Skip to the line'}</Btn>
    </div>
  );
}
