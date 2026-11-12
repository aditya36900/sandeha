import React, { useMemo, useRef } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { Html, Line, OrbitControls } from '@react-three/drei';
import * as THREE from 'three';
import { Cloud, DefectRegion } from '../api';

const DOUBT = new THREE.Color('#f2a93b');
const FAIL = new THREE.Color('#f0655a');
const SEV: Record<DefectRegion['severity'], string> = { minor: '#f2a93b', major: '#f0655a', critical: '#ff3b6b' };

// dataset coordinates are z-up; three.js is y-up
const toThree = (p: number[]) => new THREE.Vector3(p[0], p[2], -p[1]);

export function Points({ cloud, heat, dim }: { cloud: Cloud; heat?: number[] | null; dim?: boolean }) {
  const geom = useMemo(() => {
    const g = new THREE.BufferGeometry();
    const p = cloud.positions;
    const keep: number[] = [];
    for (let i = 0; i < cloud.count; i++) if (!cloud.fg || cloud.fg[i]) keep.push(i); // only the part, not the table
    const pos = new Float32Array(keep.length * 3);
    const col = new Float32Array(keep.length * 3);
    const c = new THREE.Color();
    const lift = new THREE.Color('#8f97c2');
    keep.forEach((i, j) => {
      pos[3 * j] = p[3 * i];
      pos[3 * j + 1] = p[3 * i + 2];
      pos[3 * j + 2] = -p[3 * i + 1];
      c.setRGB(cloud.colors[3 * i], cloud.colors[3 * i + 1], cloud.colors[3 * i + 2]);
      c.lerp(lift, dim ? 0.35 : 0.18); // lift very dark parts so the shape reads on the ink background
      const h = heat && heat.length === cloud.count ? heat[i] : 0;
      if (h > 0.35) c.lerp(h > 0.7 ? FAIL : DOUBT, Math.min(1, (h - 0.35) * 2));
      col[3 * j] = c.r;
      col[3 * j + 1] = c.g;
      col[3 * j + 2] = c.b;
    });
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('color', new THREE.BufferAttribute(col, 3));
    return g;
  }, [cloud, heat, dim]);
  return (
    <points geometry={geom}>
      <pointsMaterial size={0.022} vertexColors sizeAttenuation />
    </points>
  );
}

function Cameras({ cloud }: { cloud: Cloud }) {
  return (
    <group>
      {cloud.cameras.map((c, i) => {
        const v = new THREE.Vector3(c.position[0], c.position[2], -c.position[1]).multiplyScalar(0.62);
        return (
          <mesh key={i} position={v} onUpdate={m => m.lookAt(0, 0, 0)}>
            <coneGeometry args={[0.05, 0.1, 4]} />
            <meshBasicMaterial color="#f2a93b" wireframe />
          </mesh>
        );
      })}
    </group>
  );
}

export function Pulse({ at, color, delay }: { at: THREE.Vector3; color: string; delay: number }) {
  const ring = useRef<THREE.Mesh>(null);
  useFrame(({ clock }) => {
    if (!ring.current) return;
    const t = ((clock.elapsedTime + delay) % 1.6) / 1.6;
    ring.current.scale.setScalar(1 + t * 2.4);
    (ring.current.material as THREE.MeshBasicMaterial).opacity = 0.75 * (1 - t);
  });
  return (
    <group position={at}>
      <mesh>
        <sphereGeometry args={[0.035, 16, 16]} />
        <meshBasicMaterial color={color} />
      </mesh>
      <mesh ref={ring}>
        <sphereGeometry args={[0.04, 16, 16]} />
        <meshBasicMaterial color={color} transparent opacity={0.6} depthWrite={false} />
      </mesh>
    </group>
  );
}

/** A defect pinned to the part: pulsing marker on the surface, a leader line, and a label card. */
function Callout({ r, i, n, active, onPick }: { r: DefectRegion; i: number; n: number; active: boolean; onPick?: (id: string) => void }) {
  const at = toThree(r.anchor!);
  // fan labels out around the part so they never stack on top of each other
  const ang = (i / Math.max(n, 1)) * Math.PI * 2 + Math.atan2(at.z, at.x);
  const label = at.clone().add(new THREE.Vector3(Math.cos(ang) * 0.55, 0.55 + 0.12 * i, Math.sin(ang) * 0.25));
  const color = SEV[r.severity];
  return (
    <group>
      <Pulse at={at} color={color} delay={i * 0.4} />
      <Line points={[at, label]} color={color} lineWidth={active ? 2.4 : 1.4} transparent opacity={0.9} />
      <Html position={label} center zIndexRange={[20, 0]}>
        <button onClick={() => onPick?.(r.id)}
          className={`text-left whitespace-nowrap rounded-lg px-2.5 py-1.5 text-[11px] leading-tight shadow-lg backdrop-blur border ${active ? 'bg-ink/95' : 'bg-ink/80'}`}
          style={{ borderColor: color }}>
          <div className="font-semibold" style={{ color }}>{r.id} · {r.label}</div>
          <div className="text-mist">{r.severity} · {r.areaPct}% of part{r.realOdds != null ? ` · ${Math.round(r.realOdds * 100)}% real` : ''}</div>
        </button>
      </Html>
    </group>
  );
}

export function Spin({ children, sway, frozen }: { children: React.ReactNode; sway?: boolean; frozen?: boolean }) {
  const ref = useRef<THREE.Group>(null);
  useFrame(({ clock }, dt) => {
    if (!ref.current || frozen) return;
    if (sway) {
      ref.current.rotation.y = Math.sin(clock.elapsedTime * 0.45) * 0.55;
      ref.current.rotation.x = 0.35 + Math.sin(clock.elapsedTime * 0.3) * 0.12;
    } else ref.current.rotation.y += dt * 0.25;
  });
  return <group ref={ref} rotation={sway ? [0.35, 0, 0] : [0, 0, 0]}>{children}</group>;
}

export default function Twin3D({ cloud, heat, height = 420, cameras = true, regions, activeRegion, onPickRegion }: {
  cloud: Cloud; heat?: number[] | null; height?: number; cameras?: boolean;
  regions?: DefectRegion[] | null; activeRegion?: string | null; onPickRegion?: (id: string) => void;
}) {
  const pins = (regions || []).filter(r => r.anchor);
  return (
    <div style={{ height }} className="w-full rounded-xl overflow-hidden relative" role="img" aria-label="3D digital twin of the part">
      <Canvas camera={{ position: cloud.cameras.length === 0 ? [0, 0.4, 2.3] : [0, 0.6, 3.1], fov: 42 }} dpr={[1, 2]}>
        <Spin sway={cloud.cameras.length === 0} frozen={!!activeRegion}>
          <Points cloud={cloud} heat={heat} dim={pins.length > 0} />
          {cameras && <Cameras cloud={cloud} />}
          {pins.map((r, i) => <Callout key={r.id} r={r} i={i} n={pins.length} active={activeRegion === r.id} onPick={onPickRegion} />)}
        </Spin>
        <OrbitControls enablePan={false} minDistance={1.4} maxDistance={6} />
      </Canvas>
    </div>
  );
}
