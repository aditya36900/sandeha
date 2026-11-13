import React, { useEffect, useMemo, useRef, useState } from 'react';
import { api, InspectionRecord } from '../api';
import { Btn, decisionColor } from './bits';

type Item = { id: string; file: File; url: string; rec?: InspectionRecord; state: 'waiting' | 'scanning' | 'done' | 'error' };

/** Inspect photos from this computer: drop them in, click one or scan them all. Each photo goes through the same
 *  path as a board on the line. Nothing about the photo tells the station the answer. */
export default function UploadScan({ sessionId, onResult, onOpen, onError }: {
  sessionId: string; onResult: (r: InspectionRecord) => Promise<void> | void; onOpen: (rid: string) => void; onError: (m: string) => void;
}) {
  const [items, setItems] = useState<Item[]>([]);
  const [over, setOver] = useState(false);
  const [running, setRunning] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const stop = useRef(false);
  const itemsRef = useRef<Item[]>([]);
  itemsRef.current = items;
  useEffect(() => { setItems([]); }, [sessionId]);
  useEffect(() => () => itemsRef.current.forEach(i => URL.revokeObjectURL(i.url)), []);

  const add = (list: FileList | null) => {
    if (!list) return;
    const imgs = Array.from(list).filter(f => f.type.startsWith('image/')).sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
    setItems(cur => [...cur, ...imgs.map(f => ({ id: `${f.name}-${f.size}-${Math.random().toString(36).slice(2, 7)}`, file: f, url: URL.createObjectURL(f), state: 'waiting' as const }))]);
  };
  const patch = (id: string, p: Partial<Item>) => setItems(cur => cur.map(i => (i.id === id ? { ...i, ...p } : i)));
  const scanOne = async (it: Item) => {
    patch(it.id, { state: 'scanning' });
    try {
      const rec = await api.inspect(sessionId, it.file);
      patch(it.id, { state: 'done', rec });
      await onResult(rec);
      return true;
    } catch (e: any) { patch(it.id, { state: 'error' }); onError(`${it.file.name}: ${e.message}`); return false; }
  };
  const click = async (it: Item) => {
    if (running) return;
    if (it.rec) { onOpen(it.rec.id); return; }
    setRunning(true);
    await scanOne(it);
    setRunning(false);
  };
  const scanAll = async () => {
    stop.current = false;
    setRunning(true);
    for (;;) {
      const nxt = itemsRef.current.find(i => i.state === 'waiting');
      if (!nxt || stop.current) break;
      await scanOne(nxt);
      await new Promise(r => setTimeout(r, 150));
    }
    setRunning(false);
  };
  const tally = useMemo(() => {
    const done = items.filter(i => i.rec);
    return { waiting: items.filter(i => i.state === 'waiting').length, done: done.length,
      pass: done.filter(i => i.rec!.decision === 'PASS').length, doubt: done.filter(i => i.rec!.decision === 'DOUBT').length,
      fail: done.filter(i => i.rec!.decision === 'FAIL').length };
  }, [items]);

  return (
    <div>
      <div
        onDragOver={e => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
        onDrop={e => { e.preventDefault(); setOver(false); add(e.dataTransfer.files); }}
        className={`rounded-xl border-2 border-dashed p-4 transition ${over ? 'bg-raised' : ''}`} style={{ borderColor: over ? 'var(--accent)' : 'var(--line)' }}>
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1">
            <div className="font-semibold">Drop board photos here</div>
            <p className="text-sm text-mist">Same board type as this line. File names are ignored; every photo is inspected blind. Try the folder <span className="mono">demo_kit / &lt;board&gt; / 3_boards_to_inspect</span>.</p>
          </div>
          <Btn tone="accent" onClick={() => input.current?.click()}>Choose photos</Btn>
          {running ? <Btn onClick={() => { stop.current = true; }}>Stop</Btn> : <Btn tone="doubt" disabled={!tally.waiting} onClick={scanAll}>Scan all ({tally.waiting})</Btn>}
          {items.length > 0 && !running && <Btn tone="ghost" onClick={() => { items.forEach(i => URL.revokeObjectURL(i.url)); setItems([]); }}>Clear</Btn>}
        </div>
        <input ref={input} type="file" accept="image/*" multiple className="hidden" onChange={e => { add(e.target.files); e.target.value = ''; }} />
        {items.length > 0 && (
          <>
            <div className="grid grid-cols-4 sm:grid-cols-6 lg:grid-cols-8 gap-2 mt-4">
              {items.map(it => {
                const c = it.rec ? decisionColor[it.rec.decision] : it.state === 'error' ? 'var(--fail)' : 'var(--line)';
                return (
                  <button key={it.id} onClick={() => click(it)} disabled={running && !it.rec} title={it.rec ? `${it.file.name}: ${it.rec.decision}. Click to open.` : `${it.file.name}: click to scan`}
                    className="relative aspect-square overflow-hidden bg-raised text-left" style={{ borderRadius: 10, border: `2px solid ${c}` }}>
                    <img src={it.url} alt={it.file.name} className="w-full h-full object-cover" style={{ opacity: it.state === 'scanning' ? 0.55 : 1 }} />
                    {it.state === 'scanning' && <span className="sweep" />}
                    <span className="absolute left-0 right-0 bottom-0 px-1.5 py-0.5 text-[10px] mono truncate" style={{ background: it.rec ? c : 'rgb(0 0 0 / 0.6)', color: it.rec && it.rec.decision === 'DOUBT' ? '#121212' : '#fff' }}>
                      {it.rec ? it.rec.decision : it.state === 'scanning' ? 'scanning…' : it.state === 'error' ? 'failed' : it.file.name}
                    </span>
                  </button>
                );
              })}
            </div>
            <div className="flex flex-wrap gap-4 mt-3 text-sm num">
              <span className="text-mist">{tally.done} of {items.length} scanned</span>
              {tally.done > 0 && <><span style={{ color: 'var(--pass)' }}>{tally.pass} pass</span><span style={{ color: 'var(--doubt)' }}>{tally.doubt} ask a person</span><span style={{ color: 'var(--fail)' }}>{tally.fail} fail</span></>}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
