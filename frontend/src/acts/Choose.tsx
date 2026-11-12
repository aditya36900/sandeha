import React, { useEffect, useState } from 'react';
import { api, CatalogItem } from '../api';
import { useStore } from '../store';
import DoubtGauge from '../ui/DoubtGauge';
import DropZone from '../ui/DropZone';
import { Btn } from '../ui/bits';

function BringYourOwn() {
  const { start, setError } = useStore();
  const [name, setName] = useState('');
  const [label, setLabel] = useState('');
  const [good, setGood] = useState<File[]>([]);
  const [defect, setDefect] = useState<File[]>([]);
  const [test, setTest] = useState<File[]>([]);
  const [busy, setBusy] = useState('');
  const go = async () => {
    try {
      setBusy('Uploading good photos…');
      const r = await api.upload(good, 'good', undefined, name || 'My product');
      if (defect.length) { setBusy('Uploading defect examples…'); await api.upload(defect, 'defect', r.uid, undefined, label || 'defect'); }
      if (test.length) { setBusy('Uploading photos to inspect…'); await api.upload(test, 'test', r.uid); }
      setBusy('Starting…');
      await start('Upload', r.uid, 'Plant A', 0);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy('');
    }
  };
  return (
    <section className="mt-12 bg-surface rounded-2xl p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-lg font-semibold">Bring your own product</h2>
        <p className="text-mist text-sm">Use this with the parts the organisers capture. Same camera and framing for every photo works best.</p>
      </div>
      <div className="grid md:grid-cols-2 gap-3 mt-4">
        <input value={name} onChange={e => setName(e.target.value)} placeholder="Product name, e.g. Brass hex nut"
          className="bg-ink/60 rounded-xl px-4 py-2.5 placeholder:text-mist" aria-label="Product name" />
        <input value={label} onChange={e => setLabel(e.target.value)} placeholder="What the defect examples show, e.g. scratch"
          className="bg-ink/60 rounded-xl px-4 py-2.5 placeholder:text-mist" aria-label="Defect label" />
      </div>
      <div className="grid md:grid-cols-3 gap-3 mt-3">
        <DropZone label="Good parts" hint="At least 8, ideally 20 to 30. I learn what good looks like from these." files={good} onFiles={setGood} minimum={8} accent="var(--pass)" />
        <DropZone label="Defect examples (optional)" hint="Up to 5 known defects. They tune how strict I am." files={defect} onFiles={setDefect} accent="var(--fail)" />
        <DropZone label="Parts to inspect (optional)" hint="These go down the line one by one. You can add more later." files={test} onFiles={setTest} accent="var(--doubt)" />
      </div>
      <div className="flex items-center gap-3 mt-4">
        <Btn tone="doubt" disabled={good.length < 8 || !!busy} onClick={go}>Learn this product</Btn>
        <span className="text-sm text-mist">{busy || (good.length < 8 ? `${8 - good.length} more good photo${8 - good.length === 1 ? '' : 's'} needed` : 'Ready')}</span>
      </div>
    </section>
  );
}

const BOARD_NAMES: Record<string, string> = {
  pcb1: 'Ultrasonic sensor (front)', pcb2: 'Ultrasonic sensor (back)', pcb3: 'IR sensor module', pcb4: 'Li-ion charger board'
};

export default function Choose() {
  const { start, setError, views, setSessionId, setAct } = useStore();
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    api.catalog().then(setItems).catch(e => setError(String(e.message ?? e)));
  }, [setError]);

  const go = async (it: CatalogItem) => {
    setBusy(it.name);
    try {
      await start(it.source, it.name);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  const open = Object.values(views).filter(v => v.summary);
  const groups: [string, string, string][] = [
    ['VisA', 'Circuit boards', 'Real assembled PCBs (VisA, CC BY 4.0) with real defects: missing, misplaced, burnt and bent parts, extra material'],
    ['Upload', 'Your boards', 'Boards you photographed, ready to learn again']
  ];

  return (
    <div className="max-w-6xl">
      <section className="grid lg:grid-cols-[1.1fr_1fr] gap-10 items-end pt-4">
        <div>
          <h1 className="voice text-[52px] leading-[1.05] tracking-tight">
            Show me thirty good boards. I'll check every component on them, and ask before I guess.
          </h1>
          <p className="text-mist mt-5 max-w-xl text-[17px]">
            I find each resistor, capacitor, IC and connector on the board, learn how each one normally looks, then say which one is missing, moved, burnt or badly soldered, and show it in 3D. Every image comes from public datasets, so every call can be checked.
          </p>
        </div>
        <div className="bg-surface rounded-2xl p-6">
          <p className="voice text-2xl leading-snug mb-8">This is how I decide.</p>
          <DoubtGauge tauPass={0.1} tauFail={0.16} sweep />
          <p className="text-mist text-sm mt-5">
            Both lines are calibrated from your own photos, with a statistical guarantee on how often a good part is wrongly rejected. The amber band is where I hand the decision to a person, and learn from their answer.
          </p>
        </div>
      </section>

      <BringYourOwn />

      {open.length > 0 && (
        <section className="mt-12">
          <h2 className="text-lg font-semibold mb-3">Continue where you left off</h2>
          <div className="flex flex-wrap gap-3">
            {open.map(v => (
              <button key={v.id} onClick={() => { setSessionId(v.id); setAct(v.records.length ? 'line' : 'genesis'); }}
                className="flex items-center gap-3 bg-surface hover:bg-raised rounded-xl p-2 pr-5 text-left transition">
                {v.photos[0] && <img src={v.photos[0]} alt="" className="w-14 h-14 rounded-lg object-cover" />}
                <span>
                  <span className="block font-semibold">{(v.summary!.displayName ?? v.summary!.name).replace(/^\d+/, '')}</span>
                  <span className="block text-xs text-mist num">{v.summary!.plant} · {v.records.length} parts inspected</span>
                </span>
              </button>
            ))}
          </div>
        </section>
      )}

      {groups.map(([src, title, sub]) => (
        <section key={src} className="mt-12">
          <h2 className="text-lg font-semibold">{title}</h2>
          <p className="text-mist text-sm mb-4">{sub}</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            {items.filter(i => i.source === src).length === 0 && <p className="text-mist text-sm col-span-full">Nothing here yet.</p>}
            {items.filter(i => i.source === src).map(it => (
              <button key={it.source + it.name} onClick={() => go(it)} disabled={!!busy}
                className="group text-left bg-surface rounded-xl overflow-hidden hover:ring-2 hover:ring-doubt focus-visible:ring-2 focus-visible:ring-doubt transition disabled:opacity-50">
                <div className="overflow-hidden">
                  <img src={it.thumb} alt="" className="w-full aspect-square object-cover opacity-90 group-hover:opacity-100 group-hover:scale-[1.04] transition duration-300" loading="lazy" />
                </div>
                <div className="p-2.5">
                  <div className="font-semibold text-sm">{BOARD_NAMES[it.name] ?? it.name.replace(/^\d+/, '')}</div>
                  <div className="text-mist text-[11px]">{it.name}</div>
                  <div className="text-mist text-xs num">{it.defects} real defects · {it.defectTypes.length} kinds</div>
                  {busy === it.name && <div className="text-doubt text-xs mt-1">Opening…</div>}
                </div>
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
