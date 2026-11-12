import React, { Suspense, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { ContactShadows, Edges, Environment, Html, Line, OrbitControls, useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import { BoardComponent, Cloud, CompFault, DefectRegion } from '../api';
import { Points, Pulse } from './Twin3D';

export const KIND_COLOR: Record<string, string> = {
  resistor: '#5cc8b4', capacitor: '#e0b66a', IC: '#8b9cff', transistor: '#c88bff', 'diode / LED': '#ff8bd1',
  inductor: '#7fd1ff', connector: '#cfd3e6', 'hole / pad': '#6b7299', 'metal part': '#aab0cc', other: '#8f97c2'
};
export const STATUS_COLOR: Record<string, string> = {
  MISSING: '#ff3b6b', ROTATED: '#f2a93b', SHIFTED: '#f2a93b', BURNT: '#f0655a', SOLDER: '#ffd15c',
  WRONG_PART: '#ff3b6b', DAMAGED: '#f0655a', EXTRA: '#ff8b3d'
};
export const STATUS_WORD: Record<string, string> = {
  MISSING: 'missing', ROTATED: 'rotated / reversed', SHIFTED: 'moved off position', BURNT: 'burnt', SOLDER: 'solder joint',
  WRONG_PART: 'wrong part', DAMAGED: 'damaged', EXTRA: 'extra material', OK: 'ok'
};

// real component models: KiCad Packages3D (CC BY-SA 4.0 + library exception), converted STEP -> GLB
const MODEL: Record<string, string> = {
  resistor: '/models/resistor.glb', capacitor: '/models/capacitor.glb', IC: '/models/ic.glb', transistor: '/models/transistor.glb',
  'diode / LED': '/models/led.glb', inductor: '/models/inductor.glb', connector: '/models/connector.glb'
};
Object.values(MODEL).forEach(u => useGLTF.preload(u));

// data coordinates are z-up (x right, y away from camera, z up); three.js is y-up
const v3 = (p: number[]) => new THREE.Vector3(p[0], p[2], -p[1]);

/** The board itself as a solid surface: the relief grid triangulated, coloured from the photo, background cut away. */
function BoardSurface({ cloud, heat, photo }: { cloud: Cloud; heat?: number[] | null; photo?: string | null }) {
  const { invalidate } = useThree();
  const tex = useMemo(() => {
    if (!photo) return null;
    const t = new THREE.TextureLoader().load(photo, () => invalidate());
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = 4;
    return t;
  }, [photo, invalidate]);
  const geom = useMemo(() => {
    const n = cloud.grid ?? Math.round(Math.sqrt(cloud.count));
    const p = cloud.positions;
    const pos = new Float32Array(cloud.count * 3);
    const col = new Float32Array(cloud.count * 3);
    const uv = new Float32Array(cloud.count * 2);
    const c = new THREE.Color();
    const hot = new THREE.Color('#f0655a');
    for (let i = 0; i < cloud.count; i++) {
      pos[3 * i] = p[3 * i]; pos[3 * i + 1] = p[3 * i + 2]; pos[3 * i + 2] = -p[3 * i + 1];
      uv[2 * i] = (i % n) / (n - 1); uv[2 * i + 1] = 1 - Math.floor(i / n) / (n - 1);  // grid is in image order
      if (photo) c.setRGB(1, 1, 1);  // the photo supplies the colour; vertex colour only tints heat
      else c.setRGB(cloud.colors[3 * i], cloud.colors[3 * i + 1], cloud.colors[3 * i + 2]);
      const h = heat && heat.length === cloud.count ? heat[i] : 0;
      if (h > 0.45) c.lerp(hot, Math.min(0.8, (h - 0.45) * 1.6));
      col[3 * i] = c.r; col[3 * i + 1] = c.g; col[3 * i + 2] = c.b;
    }
    const idx: number[] = [];
    const fg = cloud.fg;
    for (let r = 0; r < n - 1; r++) for (let q = 0; q < n - 1; q++) {
      const a = r * n + q, b = a + 1, d = a + n, e = d + 1;
      if (fg && !(fg[a] && fg[b] && fg[d] && fg[e])) continue;
      idx.push(a, d, b, b, d, e);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('color', new THREE.BufferAttribute(col, 3));
    g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    g.setIndex(idx);
    g.computeVertexNormals();
    return g;
  }, [cloud, heat, photo]);
  return (
    <mesh geometry={geom} receiveShadow>
      <meshStandardMaterial vertexColors map={tex} roughness={0.55} metalness={0.05} side={THREE.DoubleSide} />
    </mesh>
  );
}

/** A real KiCad model fitted onto a component's measured footprint. */
function PartModel({ url, size, at, ghost, tint }: { url: string; size: [number, number, number]; at: THREE.Vector3; ghost?: boolean; tint?: string }) {
  const { scene } = useGLTF(url);
  const obj = useMemo(() => {
    const o = scene.clone(true);
    o.traverse((m: any) => {
      if (m.isMesh) {
        m.material = m.material.clone();
        if (ghost) { m.material.transparent = true; m.material.opacity = 0.22; m.material.depthWrite = false; }
        if (tint) m.material.color = new THREE.Color(m.material.color).lerp(new THREE.Color(tint), 0.7);
        m.castShadow = true;
      }
    });
    const box = new THREE.Box3().setFromObject(o);
    const s = new THREE.Vector3(); box.getSize(s);
    const long = size[0] >= size[1];
    const modelLongX = s.x >= s.y;
    const turn = long !== modelLongX;
    const fx = turn ? s.y : s.x, fy = turn ? s.x : s.y;
    const k = Math.min(size[0] / Math.max(fx, 1e-6), size[1] / Math.max(fy, 1e-6)) * 0.95;
    const g = new THREE.Group();
    o.position.set(-(box.min.x + box.max.x) / 2, -(box.min.y + box.max.y) / 2, -box.min.z);  // centre, base on the board
    const inner = new THREE.Group();
    inner.add(o);
    inner.rotation.z = turn ? Math.PI / 2 : 0;
    g.add(inner);
    g.scale.setScalar(k);
    return g;
  }, [scene, size[0], size[1], ghost, tint]);
  return <primitive object={obj} position={at} />;
}

function Part({ c, fault, hovered, setHovered, showLabel, slot, slots, selected, onSelect, dim, models }: {
  c: BoardComponent; fault?: CompFault; hovered: boolean; setHovered: (id: string | null) => void; showLabel: boolean; slot: number; slots: number;
  selected?: boolean; onSelect?: (id: string) => void; dim?: boolean; models: boolean;
}) {
  const ref = useRef<THREE.Mesh>(null);
  const b = c.box3d!;
  const pos = v3(b.center);
  const size: [number, number, number] = [b.size[0], b.size[2], b.size[1]];
  const surface = pos.clone().setZ(pos.z - size[2] / 2);
  const col = fault ? STATUS_COLOR[fault.status] ?? '#f0655a' : KIND_COLOR[c.kind] ?? '#8f97c2';
  const url = models ? MODEL[c.kind] : undefined;  // photo mode: the real pixels show the part, no stand-in model
  const labelAt = new THREE.Vector3((slot - (slots - 1) / 2) * 0.62, 1.05 + (slot % 2) * 0.32, pos.z + 0.3);
  return (
    <group>
      {url && <Suspense fallback={null}><PartModel url={url} size={size} at={surface} ghost={fault?.status === 'MISSING'} tint={fault?.status === 'BURNT' ? '#1a0d08' : undefined} /></Suspense>}
      <mesh ref={ref} position={pos} onPointerOver={e => { e.stopPropagation(); setHovered(c.id); }} onPointerOut={() => setHovered(null)}
        onClick={e => { e.stopPropagation(); onSelect?.(c.id); }}>
        <boxGeometry args={[size[0] * 1.08, size[1] * 1.08, size[2] * 1.4]} />
        <meshStandardMaterial color={selected ? '#f2a93b' : col} transparent opacity={selected ? 0.35 : dim ? 0.02 : fault ? 0.28 : models ? (url ? (hovered ? 0.18 : 0.0) : (hovered ? 0.5 : 0.2)) : (hovered ? 0.25 : 0.0)}
          emissive={fault ? col : '#000000'} emissiveIntensity={fault ? 0.9 : 0} depthWrite={false} />
        {(fault || hovered || selected || (models && !url)) && <Edges color={selected ? '#f2a93b' : col} />}
      </mesh>
      {fault && <Pulse at={pos.clone().add(new THREE.Vector3(0, 0, size[2]))} color={col} delay={slot * 0.3} />}
      {(showLabel || hovered || selected || (fault && !dim)) && (
        <>
          {fault && <Line points={[pos, labelAt]} color={col} lineWidth={1.6} />}
          <Html position={fault ? labelAt : pos.clone().add(new THREE.Vector3(0, size[1] / 2 + 0.05, 0))} center zIndexRange={[30, 0]}>
            <div className="pointer-events-none whitespace-nowrap rounded-md px-2 py-1 text-[11px] leading-tight bg-ink/90 border shadow-lg" style={{ borderColor: col }}>
              <div className="font-semibold" style={{ color: col }}>{c.id} · {c.kind}{fault ? ` · ${STATUS_WORD[fault.status]}` : ''}</div>
              {fault?.why?.[0] && <div className="text-mist max-w-[190px] whitespace-normal">{fault.why[0]}</div>}
              {!fault && hovered && <div className="text-mist">{Math.round(c.kindConfidence * 100)}% sure of the type · {c.namedBy}</div>}
            </div>
          </Html>
        </>
      )}
    </group>
  );
}

const POSE = new THREE.Euler(-0.55, 0, 0);

// a fixed, readable pose: the board tilted towards the viewer. No idle animation: the scene renders only on change.
function Sway({ children }: { children: React.ReactNode; frozen?: boolean; still?: boolean }) {
  return <group rotation={[POSE.x, 0, 0]}>{children}</group>;
}

function CameraRig({ focus, home }: { focus: THREE.Vector3 | null; home: number }) {
  const { camera, controls, invalidate } = useThree() as any;
  const goal = useRef<{ pos: THREE.Vector3; target: THREE.Vector3 } | null>(null);
  React.useEffect(() => {
    if (focus) {
      const w = focus.clone().applyEuler(POSE);
      goal.current = { target: w, pos: w.clone().add(new THREE.Vector3(0.15, 0.25, 0.95)) };
    } else {
      goal.current = { target: new THREE.Vector3(0, 0, 0), pos: new THREE.Vector3(0, 0.2, 2.6) };
    }
    invalidate();
  }, [focus?.x, focus?.y, focus?.z, home]);
  useFrame(() => {
    const g = goal.current;
    if (!g) return;
    camera.position.lerp(g.pos, 0.12);
    if (controls) { controls.target.lerp(g.target, 0.12); controls.update(); }
    if (camera.position.distanceTo(g.pos) < 0.005) goal.current = null;  // arrived: hand control back to the user
    else invalidate();
  });
  return null;
}

const MEASURE_LABEL: Record<string, string> = {
  offset: 'moved (px)', corr: 'match to golden part', dL: 'body lightness change', bodyFrac: 'body still present',
  heat: 'anomaly heat', terminalRatio: 'heat at joints vs body', termDLmin: 'duller joint (L*)', ringMetal: 'new metal around it',
};

function InfoPanel({ components, faults, watch, selected, onSelect, verdict }: {
  components: BoardComponent[]; faults: CompFault[]; watch: CompFault[]; selected: string | null; onSelect: (id: string | null) => void; verdict?: string;
}) {
  const c = components.find(x => x.id === selected);
  const f = [...faults, ...watch].find(x => x.id === selected);
  const kinds = components.reduce<Record<string, number>>((a, x) => ((a[x.kind] = (a[x.kind] ?? 0) + 1), a), {});
  return (
    <aside className="w-full lg:w-[290px] shrink-0 bg-ink/70 lg:border-l border-line p-3 text-xs space-y-3 overflow-auto">
      <div>
        <div className="text-sm font-semibold">{components.length} parts checked{verdict ? ` · board ${verdict}` : ''}</div>
        <div className="text-mist">{faults.length ? `${faults.length} fault${faults.length > 1 ? 's' : ''}` : 'no faults'}{watch.length ? ` · ${watch.length} to watch` : ''} · click any part</div>
      </div>
      {faults.length > 0 && (
        <ul className="space-y-1">
          {faults.map(x => (
            <li key={x.id}><button onClick={() => onSelect(x.id)} className={`w-full text-left rounded-lg px-2 py-1.5 border ${selected === x.id ? 'border-doubt bg-raised' : 'border-line hover:bg-raised'}`}>
              <span className="font-semibold" style={{ color: STATUS_COLOR[x.status] }}>{x.id}</span> <span className="text-mist">{x.kind}</span> · {STATUS_WORD[x.status]}
            </button></li>
          ))}
        </ul>
      )}
      {c || (f && f.status === 'EXTRA') ? (
        <div className="rounded-xl bg-raised p-2.5 space-y-1.5">
          <div className="flex justify-between items-baseline"><span className="text-sm font-semibold" style={{ color: f ? STATUS_COLOR[f.status] : KIND_COLOR[c!.kind] }}>{f?.id ?? c!.id}</span>
            <button className="text-mist hover:text-bone" onClick={() => onSelect(null)}>close</button></div>
          {c && <div><span className="text-mist">type</span> {c.kind} <span className="text-mist">({Math.round(c.kindConfidence * 100)}% sure, {c.namedBy})</span></div>}
          <div><span className="text-mist">status</span> <b style={{ color: f ? STATUS_COLOR[f.status] : 'var(--pass)' }}>{f ? STATUS_WORD[f.status] : 'as on good boards'}</b>{f?.level === 'watch' ? <span className="text-mist"> (watch only)</span> : null}</div>
          {f?.why?.[0] && <div className="text-bone/90">{f.why[0]}</div>}
          {(f as any)?.origin && <div><span className="text-mist">likely started at</span> {(f as any).origin}: <span className="text-mist">{(f as any).cause}</span></div>}
          {(f as any)?.action && <div><span className="text-mist">repair</span> {(f as any).action}</div>}
          {f?.measured && (
            <dl className="grid grid-cols-2 gap-x-2 gap-y-0.5 pt-1 border-t border-line">
              {Object.entries(MEASURE_LABEL).filter(([k]) => f.measured![k] !== undefined).map(([k, label]) => (
                <React.Fragment key={k}><dt className="text-mist">{label}</dt><dd className="num text-right">{typeof f.measured![k] === 'number' ? (f.measured![k] as number).toFixed(2) : String(f.measured![k])}</dd></React.Fragment>
              ))}
            </dl>
          )}
          {c && Object.keys(c.history).length > 0 && <div className="pt-1 border-t border-line"><span className="text-mist">on this line before:</span> {Object.entries(c.history).map(([k, v]) => `${v}× ${STATUS_WORD[k] ?? k}`).join(', ')}</div>}
        </div>
      ) : (
        <div className="space-y-1">
          <div className="text-mist">What is on this board</div>
          {Object.entries(kinds).sort((a, b) => b[1] - a[1]).map(([k, n]) => (
            <div key={k} className="flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-sm" style={{ background: KIND_COLOR[k] ?? '#8f97c2' }} />{n} {k}</div>
          ))}
          <div className="text-mist pt-2">Colours</div>
          <div className="flex flex-wrap gap-x-2 gap-y-1">
            {Object.entries(STATUS_COLOR).map(([k, col]) => <span key={k} className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ background: col }} />{STATUS_WORD[k]}</span>)}
          </div>
        </div>
      )}
    </aside>
  );
}

/** The board in 3D: solid relief surface, real component models, faults lit up and labelled. */
export default function Board3D({ cloud, components, faults, watch, regions, heat, height = 420, labels = 'faults', realistic = false, verdict, panel = true, photo }: {
  cloud: Cloud; components: BoardComponent[]; faults?: CompFault[] | null; watch?: CompFault[] | null; regions?: DefectRegion[] | null;
  heat?: number[] | null; height?: number; labels?: 'faults' | 'all'; realistic?: boolean; verdict?: string; panel?: boolean;
  photo?: string | null;
}) {
  const [models, setModels] = useState(!photo);
  const [hovered, setHovered] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [showHeat, setShowHeat] = useState(true);
  const [allLabels, setAllLabels] = useState(labels === 'all');
  const [home, setHome] = useState(0);
  const byId = useMemo(() => new Map((faults ?? []).filter(f => f.status !== 'EXTRA').map(f => [f.id, f] as const)), [faults]);
  const extras = (faults ?? []).filter(f => f.status === 'EXTRA');
  const extraPins = extras.map((e, i) => {
    const r = (regions ?? []).find(g => g.anchor && e.centroid && Math.hypot(g.centroid[0] - e.centroid[0], g.centroid[1] - e.centroid[1]) < 0.08);
    return r?.anchor ? { e, at: v3(r.anchor), i } : null;
  }).filter(Boolean) as { e: CompFault; at: THREE.Vector3; i: number }[];
  const shown = components.filter(c => c.box3d);
  const faulty = shown.filter(c => byId.has(c.id)).sort((a, b) => a.centroid[0] - b.centroid[0]).map(c => c.id);
  const selComp = shown.find(c => c.id === selected);
  const focus = selComp ? v3(selComp.box3d!.center) : null;
  const pick = (id: string | null) => { setSelected(id); if (!id) setHome(h => h + 1); };
  return (
    <div style={{ minHeight: height }} className="w-full rounded-xl overflow-hidden relative bg-gradient-to-b from-raised/60 to-ink flex flex-col lg:flex-row">
      <div className="relative flex-1 min-w-0" style={{ height }} role="img" aria-label="3D board with every component">
      <div className="absolute top-2 left-2 z-10 flex gap-1 text-[11px]">
        <button onClick={() => setShowHeat(h => !h)} className={`px-2 py-1 rounded-lg ${showHeat ? 'bg-raised text-bone' : 'bg-ink/60 text-mist'}`}>heatmap {showHeat ? 'on' : 'off'}</button>
        <button onClick={() => setAllLabels(l => !l)} className={`px-2 py-1 rounded-lg ${allLabels ? 'bg-raised text-bone' : 'bg-ink/60 text-mist'}`}>{allLabels ? 'all labels' : 'fault labels'}</button>
        <button onClick={() => setModels(m => !m)} className={`px-2 py-1 rounded-lg ${models ? 'bg-raised text-bone' : 'bg-ink/60 text-mist'}`}>{models ? 'parts: 3D models' : photo ? 'parts: this board\'s photo' : 'parts: outlines'}</button>
        <button onClick={() => pick(null)} className="px-2 py-1 rounded-lg bg-ink/60 text-mist hover:text-bone">reset view</button>
      </div>
      <Canvas frameloop="demand" shadows={realistic} camera={{ position: [0, 0.2, 2.6], fov: 40 }} dpr={[1, 1.25]} onPointerMissed={() => pick(null)}>
        <ambientLight intensity={0.35} />
        <directionalLight position={[1.5, 2.5, 3]} intensity={1.2} castShadow />
        {realistic && <Suspense fallback={null}><Environment files="/env/studio.hdr" /></Suspense>}
        <CameraRig focus={focus} home={home} />
        <Sway frozen={!!hovered} still={!!selected}>
          {cloud.grid ? <BoardSurface cloud={cloud} heat={showHeat ? heat : null} photo={photo} /> : <Points cloud={cloud} heat={showHeat ? heat : null} dim />}
          {shown.map(c => (
            <Part key={c.id} c={c} fault={byId.get(c.id)} hovered={hovered === c.id} setHovered={setHovered} showLabel={allLabels}
              slot={Math.max(0, faulty.indexOf(c.id))} slots={Math.max(1, faulty.length)}
              selected={selected === c.id} onSelect={pick} dim={!!selected && selected !== c.id} models={models} />
          ))}
          {extraPins.map(({ e, at, i }) => (
            <group key={e.id}>
              <Pulse at={at} color={STATUS_COLOR.EXTRA} delay={i * 0.3} />
              <Html position={at.clone().add(new THREE.Vector3(0, 0.2, 0.2))} center>
                <div className="pointer-events-none whitespace-nowrap rounded-md px-2 py-1 text-[11px] bg-ink/90 border" style={{ borderColor: STATUS_COLOR.EXTRA }}>
                  <span className="font-semibold" style={{ color: STATUS_COLOR.EXTRA }}>{e.id} · extra material</span>
                </div>
              </Html>
            </group>
          ))}
        </Sway>
        {realistic && <ContactShadows position={[0, -1.05, 0]} opacity={0.45} scale={4} blur={2.4} far={2} frames={1} />}
        <OrbitControls makeDefault enablePan={false} minDistance={0.4} maxDistance={5} />
      </Canvas>
      <div className="absolute left-2 bottom-1 text-[10px] text-mist/70">{photo && !models ? 'surface: this board\'s own photo, aligned to the 3D relief' : 'component models: KiCad Packages3D (CC BY-SA 4.0)'}{realistic ? ' · lighting: Poly Haven (CC0)' : ''}</div>
      </div>
      {panel && <InfoPanel components={shown} faults={faults ?? []} watch={watch ?? []} selected={selected} onSelect={pick} verdict={verdict} />}
    </div>
  );
}
