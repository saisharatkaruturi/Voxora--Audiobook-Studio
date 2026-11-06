import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { useTheme } from "@/stores/theme";

/**
 * "Sound emerging from a book": one GPU point cloud. Each particle rises from
 * the spine along a curved path, settles into the VOXORA waveform, breathes
 * with it, then drifts off into space. Everything is computed in the vertex
 * shader from per-particle seeds, so the CPU only updates a few uniforms.
 */
const vertex = /* glsl */ `
  uniform float uTime;
  uniform float uOpen;     // 0 closed .. 1 open: gates emission
  uniform float uEnergy;   // audio energy 0..1 (playback / generation)
  uniform float uRate;     // flow speed multiplier
  uniform vec2 uPointer;   // -1..1
  uniform float uAbsorb;   // 0 emit from the book .. 1 stream into the book
  uniform float uPixelRatio;
  attribute float aSeed;
  attribute float aBar;    // 0..1 position across the waveform
  attribute float aSide;   // -1 below / +1 above the centre line
  varying float vAlpha;
  varying vec3 vColor;

  float wave(float x, float t) {
    float center = 1.0 - abs(x - 0.5) * 1.7;
    float a = 0.35 + 0.65 * max(center, 0.0);
    return a * (0.55 + 0.45 * sin(t * 1.6 + x * 9.0) * cos(t * 0.7 + x * 3.0));
  }

  void main() {
    float cycle = 5.5 / uRate;
    float life = fract(uTime / cycle + aSeed);
    float emit = smoothstep(0.0, 0.25, uOpen);

    vec3 origin = vec3(0.0, 0.05, 0.12);
    float wx = (aBar - 0.5) * 3.4;
    float amp = wave(aBar, uTime) * (0.38 + uEnergy * 0.45);
    vec3 target = vec3(wx, 1.35 + aSide * amp * (0.35 + 0.65 * fract(aSeed * 7.13)), 0.0);

    // 0-0.35 rise along a curve, 0.35-0.8 live in the waveform, 0.8-1 drift away
    float rise = smoothstep(0.0, 0.35, life);
    vec3 ctrl = vec3(wx * 0.25, 1.9, 0.6);
    vec3 a = mix(origin, ctrl, rise);
    vec3 b = mix(ctrl, target, rise);
    vec3 p = mix(a, b, rise);
    float drift = smoothstep(0.8, 1.0, life);
    p += vec3(sin(aSeed * 40.0) * 0.9, 0.7 + fract(aSeed * 3.7), cos(aSeed * 23.0) * 0.5) * drift;
    p.x += sin(uTime * 0.6 + aSeed * 30.0) * 0.03;
    p.xy += uPointer * 0.12 * rise;

    vAlpha = emit * smoothstep(0.0, 0.06, life) * (1.0 - drift) * (0.55 + 0.45 * fract(aSeed * 5.3));
    // Absorb: text particles leave the document (left), become the waveform, sink into the spine.
    if (uAbsorb > 0.001) {
      float k = fract(uTime / (3.2 / uRate) + aSeed);
      vec3 src = vec3(-3.4 + sin(aSeed * 50.0) * 0.35, 0.2 + cos(aSeed * 31.0) * 0.8, 0.4);
      vec3 mid = vec3(wx * 0.8, 1.2 + aSide * amp * 0.6, 0.2);
      vec3 sink = vec3(0.0, 0.1, 0.1);
      vec3 q = k < 0.6 ? mix(src, mid, smoothstep(0.0, 0.6, k)) : mix(mid, sink, smoothstep(0.6, 1.0, k));
      p = mix(p, q, uAbsorb);
      vAlpha = mix(vAlpha, smoothstep(0.0, 0.08, k) * (1.0 - smoothstep(0.9, 1.0, k)) * (0.6 + 0.4 * fract(aSeed * 5.3)), uAbsorb);
    }
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    float size = mix(1.8, 4.2, fract(aSeed * 11.7)) * (1.0 + uEnergy * 0.6);
    gl_PointSize = size * uPixelRatio * (6.0 / -mv.z);

    vec3 orchid = vec3(0.77, 0.36, 1.0);
    vec3 ice = vec3(0.66, 0.85, 1.0);
    vec3 mint = vec3(0.37, 1.0, 0.82);
    vec3 amber = vec3(1.0, 0.72, 0.42);
    vColor = aBar < 0.5 ? mix(orchid, ice, aBar * 2.0) : mix(ice, mint, (aBar - 0.5) * 2.0);
    if (fract(aSeed * 97.0) > 0.97) vColor = amber;
  }
`;

const fragment = /* glsl */ `
  uniform float uDay;
  varying float vAlpha;
  varying vec3 vColor;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    float soft = smoothstep(0.5, 0.0, d);
    vec3 c = mix(vColor, vColor * vec3(0.62, 0.5, 0.78), uDay);
    gl_FragColor = vec4(c, soft * vAlpha * mix(1.0, 0.85, uDay));
  }
`;

export interface ParticleDrive {
  open: number; // 0..1
  energy: number; // 0..1
  rate: number; // flow speed
  absorb?: number; // 0..1
}

export function AudioParticles({ count = 1400, drive, pointer }: { count?: number; drive: React.MutableRefObject<ParticleDrive>; pointer: React.MutableRefObject<THREE.Vector2> }) {
  const material = useRef<THREE.ShaderMaterial>(null);
  const day = useTheme((s) => s.theme) === "light";
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry();
    const seeds = new Float32Array(count);
    const bars = new Float32Array(count);
    const sides = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      seeds[i] = Math.random();
      bars[i] = Math.random();
      sides[i] = Math.random() < 0.5 ? -1 : 1;
    }
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(count * 3), 3));
    g.setAttribute("aSeed", new THREE.BufferAttribute(seeds, 1));
    g.setAttribute("aBar", new THREE.BufferAttribute(bars, 1));
    g.setAttribute("aSide", new THREE.BufferAttribute(sides, 1));
    g.boundingSphere = new THREE.Sphere(new THREE.Vector3(0, 1, 0), 6);
    return g;
  }, [count]);
  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uOpen: { value: 0 },
      uEnergy: { value: 0 },
      uRate: { value: 1 },
      uPointer: { value: new THREE.Vector2() },
      uAbsorb: { value: 0 },
      uPixelRatio: { value: Math.min(window.devicePixelRatio || 1, 2) },
      uDay: { value: 0 },
    }),
    [],
  );

  useFrame((_, delta) => {
    const u = material.current?.uniforms;
    if (!u) return;
    u.uTime.value += delta;
    u.uDay.value = day ? 1 : 0;
    u.uOpen.value = THREE.MathUtils.damp(u.uOpen.value, drive.current.open, 2.5, delta);
    u.uEnergy.value = THREE.MathUtils.damp(u.uEnergy.value, drive.current.energy, 6, delta);
    u.uRate.value = THREE.MathUtils.damp(u.uRate.value, drive.current.rate, 2, delta);
    u.uAbsorb.value = THREE.MathUtils.damp(u.uAbsorb.value, drive.current.absorb ?? 0, 2.5, delta);
    (u.uPointer.value as THREE.Vector2).lerp(pointer.current, 0.05);
  });

  return (
    <points geometry={geometry} frustumCulled={false}>
      <shaderMaterial ref={material} vertexShader={vertex} fragmentShader={fragment} uniforms={uniforms} transparent depthWrite={false} blending={day ? THREE.NormalBlending : THREE.AdditiveBlending} key={day ? "day" : "night"} />
    </points>
  );
}
