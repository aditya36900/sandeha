import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { Html, Line, OrbitControls } from '@react-three/drei';
import * as THREE from 'three';
import { api } from '../api';
import { useStore } from '../store';
import { Btn, Panel, decisionColor } from '../ui/bits';
import { KIND_COLOR } from '../ui/Board3D';
import { Chip, PageHead, usePoll } from '../room/common';
import { LinePicker, Measured, useSid } from './common';

const ORDER = ['substrate', 'copper', 'mask', 'silk', 'parts', 'failures'];
const VERDICT_TONE: Record<string, string> = { MATCH: 'var(--pass)', PARTIAL: 'var(--doubt)', DIFFERENT: 'var(--fail)', 'MARKING UNREADABLE': 'var(--fail)' };

function useTexture(url: string) {
  return useMemo(() => {
    const t = new THREE.TextureLoader().load(url);
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = 4;
    return t;
  }, [url]);
}

function Layer({ url, w, h, y, opacity }: { url: string; w: number; h: number; y: number; opacity: number }) {
  const tex = useTexture(url);
  return (
    <mesh position={[0, y, 0]} rotation={[-Math.PI / 2, 0, 0]}>
      <planeGeometry args={[w, h]} />
      <meshBasicMaterial map={tex} transparent opacity={opacity} depthWrite={false} side={THREE.DoubleSide} />
    </mesh>
  );
}

function Stack({ x, visible, explode, selected, setSelected, hovered, setHovered }: {
  x: any; visible: Record<string, boolean>; explode: number; selected: string | null; setSelected: (id: string | null) => void;
  hovered: string | null; setHovered: (id: string | null) => void;
}) {
  const cur = useRef(explode);
  const [e, setE] = useState(explode);
  const { invalidate } = useThree();
  useEffect(() => { invalidate(); }, [explode, visible, selected, hovered, invalidate]);
  useFrame(() => {  // smooth explode / assemble, then stop rendering
    cur.current += (explode - cur.current) * 0.15;
    if (Math.abs(cur.current - e) > 0.002) { setE(cur.current); invalidate(); }
  });
  const W = 2.4, H = (W * x.size[1]) / x.size[0];
  const gap = 0.32 * e;
  const yOf = (key: string) => ORDER.indexOf(key) * gap;
  const pos = (c: any, key = 'parts') => new THREE.Vector3((c.centroid[0] - 0.5) * W, yOf(key) + 0.01, (c.centroid[1] - 0.5) * H);
  const byId = new Map<string, any>(x.components.map((c: any) => [c.id, c]));
  const linked = new Set<string>();
  x.edges.forEach((ed: any) => { if (ed.a === selected) linked.add(ed.b); if (ed.b === selected) linked.add(ed.a); });
  return (
    <group>
      {x.layers.filter((l: any) => visible[l.key]).map((l: any) => (
        <Layer key={l.key} url={l.image} w={W} h={H} y={yOf(l.key)} opacity={l.key === 'mask' ? 0.92 : 1} />
      ))}
      {visible.copper && x.edges.map((ed: any, i: number) => {
        const a = byId.get(ed.a), b = byId.get(ed.b);
        if (!a || !b) return null;
        const on = selected && (ed.a === selected || ed.b === selected);
        return <Line key={i} points={[pos(a, 'copper'), pos(b, 'copper')]} color={on ? '#ffd15c' : '#d68c48'} lineWidth={on ? 3 : 1} transparent opacity={selected && !on ? 0.25 : 0.9} />;
      })}
      {visible.parts && x.components.map((c: any) => {
        const fails = x.failCounts[c.id] ?? 0;
        const on = selected === c.id || linked.has(c.id) || hovered === c.id;
        const col = fails ? '#f0655a' : KIND_COLOR[c.kind] ?? '#8f97c2';
        const p = pos(c);
        return (
          <group key={c.id}>
            <mesh position={p.clone().setY(p.y + 0.03)} onClick={ev => { ev.stopPropagation(); setSelected(selected === c.id ? null : c.id); }}
              onPointerOver={ev => { ev.stopPropagation(); setHovered(c.id); }} onPointerOut={() => setHovered(null)}>
              <sphereGeometry args={[0.025 + Math.min(0.05, fails * 0.008), 16, 16]} />
              <meshBasicMaterial color={selected === c.id ? '#ffd15c' : col} transparent opacity={selected && !on ? 0.3 : 1} />
            </mesh>
            {on && (
              <Html position={p.clone().setY(p.y + 0.12)} center zIndexRange={[20, 0]}>
                <div className="pointer-events-none whitespace-nowrap rounded-md px-1.5 py-0.5 text-[10px] bg-ink/90 border" style={{ borderColor: col }}>
                  <b style={{ color: col }}>{c.id}</b> {c.kind}{fails ? ` · failed ${fails}×` : ''}
                </div>
              </Html>
            )}
          </group>
        );
      })}
      {e > 0.3 && x.layers.filter((l: any) => visible[l.key]).map((l: any) => (
        <Html key={l.key + '-tag'} position={[W / 2 + 0.08, yOf(l.key), H / 2]} zIndexRange={[10, 0]}>
          <div className="pointer-events-none whitespace-nowrap text-[11px] font-semibold text-bone/90">{l.title}</div>
        </Html>
      ))}
    </group>
  );
}

export default function XRay() {
  const [sid, setSid] = useSid();
  const { view, setError } = useStore();
  const [x] = usePoll(() => (sid ? api.xray(sid) : Promise.resolve(null)), 30000, [sid]);
  const [explode, setExplode] = useState(1);
  const [visible, setVisible] = useState<Record<string, boolean>>(Object.fromEntries(ORDER.map(k => [k, true])));
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [rid, setRid] = useState<string | null>(null);
  const [chips, setChips] = useState<any | null>(null);
  const [cBusy, setCBusy] = useState(false);
  const boards = (view?.records ?? []).filter(r => r.board).slice(-14).reverse();
  useEffect(() => { setChips(null); }, [rid]);
  const readChips = async () => {
    if (!sid || !rid) return;
    setCBusy(true);
    try { setChips(await api.chips(sid, rid)); } catch (e: any) { setError(e.message); } finally { setCBusy(false); }
  };
  if (!x) return <PageHead title="Board X-ray" sub="Loading…" />;
  if (x.status !== 'ready') return <><PageHead title="Board X-ray" aside={<LinePicker sid={sid} setSid={setSid} />} /><Panel><p className="text-mist">No component map for this line yet.</p></Panel></>;
  const sel = x.components.find((c: any) => c.id === selected);
  const links = x.edges.filter((e: any) => e.a === selected || e.b === selected).map((e: any) => (e.a === selected ? e.b : e.a));
  return (
    <div className="space-y-5">
      <PageHead title="Board X-ray" sub="The board taken apart into its physical layers, each measured from the photo: substrate, copper, solder mask, silkscreen, components, and where faults have concentrated. Copper read through the mask shows which parts are wired together, so a fault's impact zone is visible."
        aside={<div className="flex gap-2 items-center"><LinePicker sid={sid} setSid={setSid} /><Measured /></div>} />
      <div className="grid xl:grid-cols-[minmax(0,1fr)_320px] gap-5 items-start">
        <Panel>
          <div className="flex flex-wrap gap-2 items-center mb-3">
            <Btn tone="doubt" onClick={() => setExplode(e => (e > 0.5 ? 0 : 1))}>{explode > 0.5 ? 'Assemble the board' : 'Explode into layers'}</Btn>
            {x.layers.map((l: any) => (
              <label key={l.key} className="flex items-center gap-1.5 text-xs px-2 py-1 rounded-lg bg-raised cursor-pointer" title={l.what}>
                <input type="checkbox" checked={visible[l.key]} onChange={ev => setVisible(v => ({ ...v, [l.key]: ev.target.checked }))} />{l.title}
              </label>
            ))}
          </div>
          <div className="h-[560px] rounded-xl overflow-hidden bg-gradient-to-b from-raised/50 to-ink">
            <Canvas frameloop="demand" camera={{ position: [0, 2.2, 2.6], fov: 40 }} dpr={[1, 1.25]} onPointerMissed={() => setSelected(null)}>
              <Stack x={x} visible={visible} explode={explode} selected={selected} setSelected={setSelected} hovered={hovered} setHovered={setHovered} />
              <OrbitControls enablePan={false} minDistance={1.2} maxDistance={6} target={[0, 0.7 * explode, 0]} />
            </Canvas>
          </div>
          <p className="text-xs text-mist mt-2">{x.note} Copper covers {x.coverage.copperPct}% of the board, solder mask {x.coverage.maskPct}%, silkscreen {x.coverage.silkPct}%, parts {x.coverage.partsPct}%.</p>
        </Panel>
        <div className="space-y-4">
          <Panel title="Layers">
            <ul className="space-y-2 text-xs">{x.layers.map((l: any) => <li key={l.key}><b className="text-sm">{l.title}</b><div className="text-mist">{l.what}</div></li>)}</ul>
          </Panel>
          <Panel title={sel ? `${sel.id} · ${sel.kind}` : 'Click a part'}>
            {sel ? (
              <div className="text-sm space-y-2">
                <div className="text-mist text-xs">{Math.round(sel.kindConfidence * 100)}% sure of the type · {sel.namedBy}</div>
                <div><b>Wired to</b> (through visible copper): {links.length ? links.join(', ') : <span className="text-mist">no visible copper link</span>}</div>
                <div><b>Failed on this line:</b> {x.failCounts[sel.id] ? `${x.failCounts[sel.id]} of ${x.boards} boards` : 'never'}</div>
                {x.failCounts[sel.id] > 0 && links.length > 0 && <div className="text-doubt text-xs">Impact zone: a fault here sits on the same copper as {links.join(', ')}; check them on the next rejected board.</div>}
              </div>
            ) : <p className="text-mist text-sm">Dots are parts; bigger and red means it failed more often. Orange lines are copper links between parts. {x.nets.length} nets traced.</p>}
          </Panel>
        </div>
      </div>
      <Panel title="Chip identity check" aside={<span className="text-xs text-mist">markings read by the local VLM</span>}>
        <p className="text-sm text-mist mb-3">A wrong, re-marked, counterfeit or burnt chip can still look like "an IC". Reading its marking catches it: on pcb4 every good board read the same marking, and every burnt board read differently or not at all.</p>
        <div className="flex gap-2 flex-wrap mb-3">
          {boards.map(r => (
            <button key={r.id} onClick={() => setRid(r.id)} className={`rounded-lg overflow-hidden border-2 ${rid === r.id ? 'border-doubt' : 'border-transparent'}`} title={`${r.id} · ${r.decision}`}>
              <img src={r.image_url} alt="" className="w-14 h-14 object-cover" />
              <div className="text-[10px] font-semibold" style={{ color: decisionColor[r.decision] }}>{r.decision}</div>
            </button>
          ))}
        </div>
        <Btn tone="doubt" disabled={!rid || cBusy} onClick={readChips}>{cBusy ? 'Reading markings (about 10 s per chip)…' : rid ? `Read the chips on ${rid.split('-').pop()}` : 'Pick a board above'}</Btn>
        {chips && !chips.available && <p className="text-mist text-sm mt-2">Not available (no component map or local model).</p>}
        {chips?.available && (
          <div className="overflow-x-auto mt-3">
            <table className="w-full text-sm num">
              <thead className="text-mist text-xs text-left"><tr><th className="py-1">Chip</th><th>Golden board says</th><th>This board says</th><th>Similarity</th><th>Verdict</th></tr></thead>
              <tbody>
                {chips.chips.map((c: any) => (
                  <tr key={c.id} className="border-t border-line">
                    <td className="py-1.5"><b>{c.id}</b> <span className="text-mist">{c.kind}</span></td>
                    <td className="font-mono">{c.expected || '—'}</td><td className="font-mono">{c.read || '—'}</td>
                    <td>{Math.round(c.similarity * 100)}%</td><td><Chip tone={VERDICT_TONE[c.verdict] ?? 'var(--mist)'}>{c.verdict.toLowerCase()}</Chip></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-xs text-mist mt-2">{chips.note}</p>
          </div>
        )}
      </Panel>
    </div>
  );
}
