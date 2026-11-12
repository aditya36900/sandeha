import React, { useMemo, useRef } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import * as THREE from 'three';

/** Reference photos arranged as a slowly turning ring of light panels (products without camera poses). */
function Ring({ photos }: { photos: string[] }) {
  const ref = useRef<THREE.Group>(null);
  const textures = useMemo(() => photos.map(src => new THREE.TextureLoader().load(src)), [photos]);
  useFrame((_, dt) => {
    if (ref.current) ref.current.rotation.y += dt * 0.12;
  });
  const n = Math.max(photos.length, 1);
  const r = Math.max(1.6, n * 0.09);
  return (
    <group ref={ref}>
      {textures.map((t, i) => {
        const a = (i / n) * Math.PI * 2;
        const y = ((i % 3) - 1) * 0.42;
        return (
          <mesh key={i} position={[Math.sin(a) * r, y, Math.cos(a) * r]} rotation={[0, a, 0]}>
            <planeGeometry args={[0.62, 0.62]} />
            <meshBasicMaterial map={t} side={THREE.DoubleSide} transparent opacity={0.92} />
          </mesh>
        );
      })}
    </group>
  );
}

export default function Lightbox3D({ photos, height = 420 }: { photos: string[]; height?: number }) {
  return (
    <div style={{ height }} className="w-full rounded-xl overflow-hidden" role="img" aria-label="Reference photos">
      <Canvas camera={{ position: [0, 0.4, 4.2], fov: 50 }} dpr={[1, 2]}>
        <Ring photos={photos} />
      </Canvas>
    </div>
  );
}
