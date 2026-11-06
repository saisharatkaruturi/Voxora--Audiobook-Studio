import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { brandGradientTexture, pageEdgeTexture } from "@/components/3d/materials";

/** Book dimensions (scene units). */
const PW = 1.22; // page width
const PH = 1.72; // page height
const PD = 0.1; // page block depth per half
const CW = 1.3; // cover width
const CH = 1.82; // cover height
const CT = 0.035; // cover thickness

export interface BookDrive {
  open: number; // 0 closed .. 1 open
  pageActivity: number; // how often/strongly loose pages move (0 calm .. 1 busy)
  breathe: number; // playback breathing 0..1
}

function coverTexture(): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = 512;
  c.height = 720;
  const x = c.getContext("2d")!;
  const bg = x.createLinearGradient(0, 0, 512, 720);
  bg.addColorStop(0, "#1c1530");
  bg.addColorStop(1, "#0d0f16");
  x.fillStyle = bg;
  x.fillRect(0, 0, 512, 720);
  // soft vignette
  const v = x.createRadialGradient(256, 300, 40, 256, 360, 420);
  v.addColorStop(0, "rgba(196,92,255,0.14)");
  v.addColorStop(1, "rgba(0,0,0,0)");
  x.fillStyle = v;
  x.fillRect(0, 0, 512, 720);
  // mark: page + waveform
  const g = x.createLinearGradient(170, 250, 350, 380);
  g.addColorStop(0, "#0B3048");
  g.addColorStop(1, "#B9F12F");
  x.fillStyle = g;
  x.beginPath();
  x.moveTo(250, 395);
  x.bezierCurveTo(220, 375, 190, 370, 165, 378);
  x.lineTo(165, 280);
  x.bezierCurveTo(190, 272, 220, 277, 250, 297);
  x.closePath();
  x.fill();
  [[266, 300, 80], [290, 280, 120], [314, 310, 60], [338, 328, 26]].forEach(([bx, by, bh]) => {
    x.beginPath();
    x.roundRect(bx, by, 14, bh, 7);
    x.fill();
  });
  x.fillStyle = "rgba(234,247,255,0.92)";
  x.font = "600 40px Sora, Inter, sans-serif";
  x.textAlign = "center";
  x.letterSpacing = "12px";
  x.fillText("VOXORA", 262, 500);
  x.fillStyle = "rgba(157,168,184,0.8)";
  x.font = "italic 22px Fraunces, Georgia, serif";
  x.letterSpacing = "0px";
  x.fillText("Where stories find their voice.", 256, 548);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}

function printedTexture(): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = 256;
  c.height = 360;
  const x = c.getContext("2d")!;
  x.fillStyle = "#f3ebdf";
  x.fillRect(0, 0, 256, 360);
  x.fillStyle = "rgba(60,50,70,0.16)";
  for (let y = 46, i = 0; y < 320; y += 13, i++) {
    const w = i % 7 === 6 ? 90 : 170 + ((i * 37) % 20);
    x.fillRect(38, y, w, 3);
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

/** One loose page hinged at the spine; its vertices bend as it lifts. */
function LoosePage({ dir, z, index, drive, paper }: { dir: 1 | -1; z: number; index: number; drive: React.MutableRefObject<BookDrive>; paper: THREE.Material }) {
  const mesh = useRef<THREE.Mesh>(null);
  const geo = useMemo(() => {
    const g = new THREE.PlaneGeometry(PW * 0.985, PH * 0.975, 28, 1);
    g.translate((dir * PW * 0.985) / 2, 0, 0);
    return g;
  }, [dir]);
  const base = useMemo(() => Float32Array.from(geo.attributes.position.array as Float32Array), [geo]);
  const state = useRef({ next: 2 + index * 2.7, start: -10, dur: 1.8, amp: 0.5 });

  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    const d = drive.current;
    const s = state.current;
    if (t > s.next && d.open > 0.9) {
      s.start = t;
      s.dur = 1.6 + Math.random() * 0.8;
      s.amp = (0.25 + Math.random() * 0.35) * (1 + d.pageActivity * 1.2);
      s.next = t + s.dur + (d.pageActivity > 0.5 ? 1.2 : 5 + Math.random() * 5);
    }
    const k = Math.min(1, Math.max(0, (t - s.start) / s.dur));
    const lift = Math.sin(k * Math.PI) ** 2 * s.amp + (0.012 + d.breathe * 0.03) * (1 + Math.sin(t * 1.3 + index)) * d.open;
    const pos = geo.attributes.position.array as Float32Array;
    for (let i = 0; i < pos.length; i += 3) {
      const u = Math.abs(base[i]) / PW; // 0 at spine .. 1 at edge
      pos[i + 2] = base[i + 2] + lift * Math.sin(u * Math.PI * 0.5) ** 1.6 * 0.9;
      pos[i] = base[i] * (1 - lift * 0.12 * u);
    }
    geo.attributes.position.needsUpdate = true;
    geo.computeVertexNormals();
  });

  return <mesh ref={mesh} geometry={geo} material={paper} position={[0, 0, z]} castShadow />;
}

function Half({ dir, drive, mats }: { dir: 1 | -1; drive: React.MutableRefObject<BookDrive>; mats: ReturnType<typeof useBookMaterials> }) {
  const group = useRef<THREE.Group>(null);
  useFrame((_, delta) => {
    if (!group.current) return;
    const o = drive.current.open;
    // Right half: 0 (flat) -> -0.26 (V toward camera). Left half folds from PI (closed on top) -> 0.26.
    const target = dir === 1 ? -0.44 * o - 0.02 : Math.PI * (1 - o) * 0.985 + 0.44 * o + 0.02;
    group.current.rotation.y = THREE.MathUtils.damp(group.current.rotation.y, target, 4, delta);
  });
  return (
    <group ref={group} rotation={[0, dir === 1 ? 0 : Math.PI * 0.985, 0]}>
      {/* cover board */}
      <mesh position={[(dir * CW) / 2, 0, -PD - CT / 2]} material={mats.cover} castShadow receiveShadow>
        <boxGeometry args={[CW, CH, CT]} />
      </mesh>
      {/* outside of the cover (branded) */}
      <mesh position={[(dir * CW) / 2, 0, -PD - CT - 0.0015]} rotation={[0, Math.PI, 0]} material={dir === -1 ? mats.coverFace : mats.backFace}>
        <planeGeometry args={[CW * 0.999, CH * 0.999]} />
      </mesh>
      {/* emissive edge line on the outside of the cover */}
      <mesh position={[(dir * CW) / 2, -CH * 0.43, -PD - CT - 0.003]} rotation={[0, Math.PI, 0]} material={mats.accent}>
        <planeGeometry args={[CW * 0.62, 0.012]} />
      </mesh>
      {/* page block */}
      <mesh position={[(dir * PW) / 2, 0, -PD / 2]} material={mats.pageBlock} castShadow receiveShadow>
        <boxGeometry args={[PW, PH, PD]} />
      </mesh>
      {/* top pages that breathe and occasionally lift */}
      {(dir === 1 ? [0, 1] : [0]).map((i) => (
        <LoosePage key={i} dir={dir} z={0.002 + i * 0.004} index={i + (dir === 1 ? 0 : 2)} drive={drive} paper={mats.paper} />
      ))}
    </group>
  );
}

function useBookMaterials() {
  return useMemo(() => {
    const edge = pageEdgeTexture();
    const paperFace = new THREE.MeshStandardMaterial({ color: "#f4ece0", roughness: 0.92 });
    const edgeMat = new THREE.MeshStandardMaterial({ map: edge, roughness: 0.95 });
    return {
      cover: new THREE.MeshPhysicalMaterial({ color: "#16121f", roughness: 0.55, metalness: 0.3, clearcoat: 0.45, clearcoatRoughness: 0.4, sheen: 0.4, sheenColor: new THREE.Color("#6a3a8f") }),
      coverFace: new THREE.MeshPhysicalMaterial({ map: coverTexture(), roughness: 0.5, metalness: 0.2, clearcoat: 0.5, clearcoatRoughness: 0.35 }),
      backFace: new THREE.MeshPhysicalMaterial({ color: "#120f1a", roughness: 0.6, metalness: 0.25, clearcoat: 0.3 }),
      accent: new THREE.MeshBasicMaterial({ map: brandGradientTexture(), toneMapped: false }),
      spine: new THREE.MeshBasicMaterial({ color: "#ffffff", toneMapped: false, transparent: true, opacity: 0.9 }),
      // box faces: +x, -x, +y, -y, +z (page top), -z
      pageBlock: [edgeMat, edgeMat, edgeMat, edgeMat, paperFace, paperFace],
      paper: new THREE.MeshStandardMaterial({ map: printedTexture(), roughness: 0.9, side: THREE.DoubleSide }),
    };
  }, []);
}

/** The VOXORA Book: a physical, hinged book whose pages breathe and lift. */
export function Book3D({ drive }: { drive: React.MutableRefObject<BookDrive> }) {
  const mats = useBookMaterials();
  const gutter = useRef<THREE.Mesh>(null);
  useFrame(() => {
    if (gutter.current) (gutter.current.material as THREE.MeshBasicMaterial).opacity = 0.2 + drive.current.open * 0.75;
  });
  return (
    <group>
      <Half dir={1} drive={drive} mats={mats} />
      <Half dir={-1} drive={drive} mats={mats} />
      {/* spine */}
      <mesh position={[0, 0, -PD - CT / 2]} material={mats.cover}>
        <boxGeometry args={[0.07, CH, CT * 1.2]} />
      </mesh>
      {/* light along the gutter: purple -> mint */}
      <mesh ref={gutter} position={[0, 0, 0.02]} rotation={[0, 0, Math.PI / 2]}>
        <planeGeometry args={[PH * 0.96, 0.018]} />
        <meshBasicMaterial map={mats.accent.map} toneMapped={false} transparent opacity={0.9} />
      </mesh>
    </group>
  );
}
