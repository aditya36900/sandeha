import React, { useMemo, useRef, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { Html, OrbitControls } from '@react-three/drei';
import * as THREE from 'three';
import { Galaxy } from '../api';

const PRODUCT_TINTS = ['#9aa6e0', '#c3b0f0', '#86c3e6', '#e2cfa8', '#a8dccf'];
const DEC = { PASS: '#5cc8b4', FAIL: '#f0655a', DOUBT: '#f2a93b', HOLD: '#8b9cff' } as const;

function Starfield() {
  const geom = useMemo(() => {
    const n = 600;
    const p = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const r = 9 + Math.random() * 6;
      const t = Math.random() * Math.PI * 2;
      const u = Math.acos(2 * Math.random() - 1);
      p.set([r * Math.sin(u) * Math.cos(t), r * Math.sin(u) * Math.sin(t), r * Math.cos(u)], i * 3);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(p, 3));
    return g;
  }, []);
  return <points geometry={geom}><pointsMaterial size={0.03} color="#5a6496" sizeAttenuation /></points>;
}

function Constellation({ idx, pts, g, centre, onHover }: {
  idx: number[]; pts: THREE.Vector3[]; g: Galaxy; centre: THREE.Vector3; onHover: (i: number | null) => void;
}) {
  const ref = useRef<THREE.Group>(null);
  useFrame((_, dt) => { if (ref.current) ref.current.rotation.y += dt * 0.12; });
  const refIdx = idx.filter(i => g.points[i].kind === 'reference');
  const lineGeom = useMemo(() => {
    const seg: number[] = [];
    refIdx.forEach(i => {
      let best = -1, bd = Infinity;
      refIdx.forEach(j => { if (j !== i) { const d = pts[i].distanceTo(pts[j]); if (d < bd) { bd = d; best = j; } } });
      if (best >= 0) seg.push(...pts[i].toArray(), ...pts[best].toArray());
    });
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(seg), 3));
    return geo;
  }, [idx, pts]);
  const p0 = g.points[idx[0]];
  const tint = PRODUCT_TINTS[p0.productIndex % PRODUCT_TINTS.length];
  return (
    <group position={centre}>
      <group ref={ref}>
        <lineSegments geometry={lineGeom}><lineBasicMaterial color="#6c78b8" transparent opacity={0.4} /></lineSegments>
        {idx.map(i => g.points[i].kind === 'reference' ? (
          <mesh key={i} position={pts[i]}>
            <sphereGeometry args={[0.07, 10, 10]} />
            <meshBasicMaterial color={tint} />
          </mesh>
        ) : (
          <mesh key={i} position={pts[i]} onPointerOver={e => { e.stopPropagation(); onHover(i); }} onPointerOut={() => onHover(null)}>
            <octahedronGeometry args={[0.12, 0]} />
            <meshBasicMaterial color={DEC[g.points[i].decision ?? 'PASS']} />
          </mesh>
        ))}
      </group>
      <Html position={[0, -1.9, 0]} center zIndexRange={[10, 0]}>
        <div className="voice text-2xl whitespace-nowrap pointer-events-none select-none" style={{ color: tint }}>
          {g.products[p0.productIndex]?.name.replace(/^\d+/, '')}
        </div>
      </Html>
    </group>
  );
}

function Scene({ g, onHover }: { g: Galaxy; onHover: (i: number | null) => void }) {
  // one constellation per product, side by side, each turning around its own centre
  const groups = useMemo(() => {
    const by: Record<number, number[]> = {};
    g.points.forEach((p, i) => (by[p.productIndex] ??= []).push(i));
    const keys = Object.keys(by).map(Number).sort((a, b) => a - b);
    const gap = 4.2;
    return keys.map((k, n) => {
      const idx = by[k];
      const P = idx.map(i => new THREE.Vector3(...(g.points[i].position as [number, number, number])));
      const c = P.reduce((a, v) => a.add(v.clone()), new THREE.Vector3()).multiplyScalar(1 / P.length);
      const pts: THREE.Vector3[] = [];
      idx.forEach((i, m) => { pts[i] = P[m].clone().sub(c).multiplyScalar(1.45); });
      return { idx, pts, centre: new THREE.Vector3((n - (keys.length - 1) / 2) * gap, 0.2, 0) };
    });
  }, [g]);
  return <>{groups.map((G, k) => <Constellation key={k} idx={G.idx} pts={G.pts} g={g} centre={G.centre} onHover={onHover} />)}</>;
}

export default function Galaxy3D({ g, height = 480 }: { g: Galaxy; height?: number }) {
  const [hover, setHover] = useState<number | null>(null);
  const hp = hover !== null ? g.points[hover] : null;
  return (
    <div className="relative rounded-xl overflow-hidden" style={{ height }}>
      <Canvas camera={{ position: [0, 0.6, 6.4], fov: 50 }} dpr={[1, 2]}>
        <Starfield />
        <Scene g={g} onHover={setHover} />
        <OrbitControls enablePan={false} minDistance={3} maxDistance={14} />
      </Canvas>
      {hp && (
        <div className="absolute top-3 right-3 bg-raised rounded-xl p-2 w-44 text-sm pointer-events-none">
          {hp.image && <img src={hp.image} alt="" className="rounded-lg mb-1" />}
          <div>{hp.product.replace(/^\d+/, '')} · {hp.decision?.toLowerCase()}</div>
          <div className="text-mist text-xs">truth: {hp.truth === 1 ? 'defect' : hp.truth === 0 ? 'good' : 'unknown'}</div>
        </div>
      )}
    </div>
  );
}
