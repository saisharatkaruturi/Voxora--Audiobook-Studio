import { useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import { AudioParticles, type ParticleDrive } from "@/components/3d/AudioParticles";
import { Book3D, type BookDrive } from "@/components/3d/Book3D";
import { glowTexture } from "@/components/3d/materials";

/** closed: floating shut · open: idle story · flowing: generating · playing: audio-reactive · absorb: a book is being brought in · sealed: closes after absorbing */
export type SceneMode = "closed" | "open" | "flowing" | "playing" | "absorb" | "sealed";

export interface HeroSceneProps {
  mode?: SceneMode;
  /** Live audio level 0..1 (player); a deterministic simulation is used otherwise. */
  level?: () => number;
  className?: string;
  particles?: number;
  /** Camera distance multiplier (bigger = book appears smaller). */
  zoom?: number;
  interactive?: boolean;
}

const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

function Rig({ mode, level, interactive, pointer }: { mode: SceneMode; level?: () => number; interactive: boolean; pointer: React.MutableRefObject<THREE.Vector2> }) {
  const book = useRef<THREE.Group>(null);
  const glow = useRef<THREE.Sprite>(null);
  const spineLight = useRef<THREE.PointLight>(null);
  const frontFill = useRef<THREE.PointLight>(null);
  const { camera } = useThree();
  const baseCam = useMemo(() => camera.position.clone(), [camera]);
  const reduced = useMemo(reducedMotion, []);
  const bookDrive = useRef<BookDrive>({ open: 0, pageActivity: 0, breathe: 0 });
  const particleDrive = useRef<ParticleDrive>({ open: 0, energy: 0.15, rate: 1 });
  const glowTex = useMemo(glowTexture, []);
  const start = useRef<number | null>(null);

  useFrame(({ clock }, delta) => {
    const t = clock.elapsedTime;
    if (start.current === null) start.current = t;
    const since = t - start.current;
    // Signature sequence: closed & floating, then open (after a beat), light, particles.
    const wantOpen = mode === "closed" || mode === "sealed" ? 0 : reduced || since > 0.9 ? 1 : 0;
    const simulated = 0.3 + 0.25 * Math.sin(t * 2.1) * Math.sin(t * 0.7 + 1);
    const energy = mode === "playing" ? (level ? level() : simulated) : mode === "flowing" || mode === "absorb" ? 0.35 + 0.2 * Math.sin(t * 1.7) : mode === "sealed" ? 0.6 : 0.12;
    bookDrive.current.open = THREE.MathUtils.damp(bookDrive.current.open, wantOpen, reduced ? 20 : 1.6, delta);
    bookDrive.current.pageActivity = mode === "flowing" ? 1 : mode === "playing" ? 0.3 : 0;
    bookDrive.current.breathe = mode === "playing" ? energy : 0.2;
    particleDrive.current.open = bookDrive.current.open > 0.75 || mode === "absorb" ? 1 : 0;
    particleDrive.current.absorb = mode === "absorb" ? 1 : 0;
    particleDrive.current.energy = energy;
    particleDrive.current.rate = reduced ? 0.4 : mode === "flowing" || mode === "absorb" ? 2 : mode === "playing" ? 1.2 + energy : 1;

    if (book.current) {
      const p = interactive && !reduced ? pointer.current : new THREE.Vector2();
      const float = reduced ? 0 : Math.sin(t * 0.8) * 0.06;
      const shut = 1 - bookDrive.current.open;
      // A closed book occupies only the right half of its local space: re-centre it and lift it.
      book.current.position.x = THREE.MathUtils.damp(book.current.position.x, -shut * 0.66, 3, delta);
      book.current.position.y = THREE.MathUtils.damp(book.current.position.y, float + shut * 0.4, 3, delta);
      book.current.rotation.y = THREE.MathUtils.damp(book.current.rotation.y, -0.38 + (reduced ? 0 : Math.sin(t * 0.25) * 0.1) + p.x * 0.3, 2.5, delta);
      book.current.rotation.x = THREE.MathUtils.damp(book.current.rotation.x, -0.2 - p.y * 0.16, 2.5, delta);
      book.current.rotation.z = THREE.MathUtils.damp(book.current.rotation.z, reduced ? 0 : Math.sin(t * 0.33) * 0.03, 2, delta);
    }
    const o = mode === "sealed" ? Math.max(bookDrive.current.open, 0.35) : bookDrive.current.open;
    if (glow.current) {
      const s = (0.4 + o * 2.2) * (1 + energy * 0.25);
      glow.current.scale.set(s, s * 0.9, 1);
      (glow.current.material as THREE.SpriteMaterial).opacity = o * (0.32 + energy * 0.28);
    }
    if (spineLight.current) spineLight.current.intensity = o * (0.9 + energy * 2.2);
    if (frontFill.current) frontFill.current.intensity = (1 - bookDrive.current.open) * 9;
    if (!reduced) {
      // subtle cinematic camera drift
      camera.position.x = baseCam.x + Math.sin(t * 0.13) * 0.12 + (interactive ? pointer.current.x * 0.15 : 0);
      camera.position.y = baseCam.y + Math.sin(t * 0.17) * 0.06 + (interactive ? pointer.current.y * 0.1 : 0);
      camera.lookAt(0, 0.45, 0);
    }
  });

  return (
    <>
      <ambientLight intensity={0.35} />
      <directionalLight position={[2.5, 4, 5]} intensity={1.1} color="#ffffff" />
      <pointLight position={[-3.2, 1.6, -1.2]} intensity={28} color="#C45CFF" distance={12} />
      <pointLight position={[3.2, 0.4, 1.8]} intensity={14} color="#F3EFFA" distance={12} />
      <pointLight ref={frontFill} position={[0.4, 1.6, 3.2]} intensity={0} color="#e9e2ff" distance={9} />
      <group ref={book}>
        <Book3D drive={bookDrive} />
        <pointLight ref={spineLight} position={[0, 0.2, 0.7]} intensity={0} color="#e3c9ff" distance={4} />
        <sprite ref={glow} position={[0, 0.95, 0.05]}>
          <spriteMaterial map={glowTex} transparent depthWrite={false} blending={THREE.AdditiveBlending} opacity={0} />
        </sprite>
      </group>
      <AudioParticles count={reduced ? 350 : 1400} drive={particleDrive} pointer={pointer} />
    </>
  );
}

/**
 * The VOXORA 3D stage. Pauses rendering whenever it's off-screen or the tab is hidden.
 */
export default function HeroScene({ mode = "open", level, className, zoom = 1, interactive = true }: HeroSceneProps) {
  const wrap = useRef<HTMLDivElement>(null);
  const pointer = useRef(new THREE.Vector2());
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => setVisible(e.isIntersecting && document.visibilityState === "visible"), { threshold: 0.01 });
    io.observe(el);
    const onVis = () => setVisible(document.visibilityState === "visible" && el.getBoundingClientRect().bottom > 0);
    document.addEventListener("visibilitychange", onVis);
    const onMove = (e: PointerEvent) => {
      pointer.current.set((e.clientX / window.innerWidth) * 2 - 1, -((e.clientY / window.innerHeight) * 2 - 1));
    };
    if (interactive) window.addEventListener("pointermove", onMove, { passive: true });
    return () => {
      io.disconnect();
      document.removeEventListener("visibilitychange", onVis);
      window.removeEventListener("pointermove", onMove);
    };
  }, [interactive]);

  return (
    <div ref={wrap} className={className} aria-hidden>
      <Canvas
        frameloop={visible ? "always" : "never"}
        dpr={[1, 1.75]}
        gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
        camera={{ position: [0, 1.0, 6.1 * zoom], fov: 32 }}
        onCreated={({ gl }) => {
          gl.toneMapping = THREE.ACESFilmicToneMapping;
          gl.toneMappingExposure = 1.05;
        }}
      >
        <Rig mode={mode} level={level} interactive={interactive} pointer={pointer} />
      </Canvas>
    </div>
  );
}
