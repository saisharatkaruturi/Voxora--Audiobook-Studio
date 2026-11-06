import { useEffect, useRef } from "react";
import { brand } from "@/config/brand";
import { cn } from "@/utils/format";

/**
 * The VOXORA Book: the signature brand animation.
 *
 *   BOOK → PAGES OPEN → LIGHT EMERGES → AUDIO PARTICLES → WAVEFORM
 *
 * Pure CSS 3D for the book, a canvas for the particles (no WebGL dependency).
 * `flowing` keeps particles streaming out of the book (work in progress);
 * otherwise they settle into the waveform and breathe. Honors reduced motion.
 */
export function VoxoraBook({ size = 280, flowing = false, className, label }: { size?: number; flowing?: boolean; className?: string; label?: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const flowRef = useRef(flowing);
  flowRef.current = flowing;

  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const ctx = el.getContext("2d");
    if (!ctx) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const W = size * 1.5;
    const H = size;
    el.width = W * dpr;
    el.height = H * dpr;
    ctx.scale(dpr, dpr);

    const origin = { x: W / 2, y: H * 0.66 };
    const BARS = 28;
    const waveY = H * 0.26;
    const span = W * 0.78;
    const COUNT = 140;
    const start = performance.now();
    const openDelay = reduced ? 0 : 700; // let the covers open first

    type P = { bar: number; frac: number; born: number; life: number; jitter: number };
    const particles: P[] = Array.from({ length: COUNT }, (_, i) => ({
      bar: i % BARS,
      frac: Math.random(),
      born: openDelay + Math.random() * 900,
      life: 2600 + Math.random() * 1800,
      jitter: Math.random() * Math.PI * 2,
    }));

    const barX = (b: number) => W / 2 - span / 2 + (b + 0.5) * (span / BARS);
    const amp = (b: number, t: number) => {
      const center = 1 - Math.abs(b - (BARS - 1) / 2) / (BARS / 2);
      return (0.25 + 0.75 * center) * (0.55 + 0.45 * Math.sin(t / 420 + b * 0.55)) * H * 0.16;
    };
    const color = (x: number, a: number) => {
      const k = Math.min(1, Math.max(0, (x - (W / 2 - span / 2)) / span));
      const r = Math.round(196 + (95 - 196) * k);
      const g = Math.round(92 + (255 - 92) * k);
      const bl = Math.round(255 + (210 - 255) * k);
      return `rgba(${r},${g},${bl},${a})`;
    };
    const ease = (t: number) => 1 - Math.pow(1 - t, 3);

    let raf = 0;
    const draw = (now: number) => {
      const t = now - start;
      ctx.clearRect(0, 0, W, H);
      // light emerging from the spine
      const glow = Math.min(1, Math.max(0, (t - openDelay * 0.6) / 700));
      if (glow > 0) {
        const g = ctx.createRadialGradient(origin.x, origin.y, 0, origin.x, origin.y - H * 0.1, H * 0.55);
        g.addColorStop(0, `rgba(234,247,255,${0.35 * glow})`);
        g.addColorStop(0.35, `rgba(196,92,255,${0.18 * glow})`);
        g.addColorStop(1, "rgba(8,9,13,0)");
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, W, H);
      }
      for (const p of particles) {
        let age = t - p.born;
        if (age < 0) continue;
        if (flowRef.current && age > p.life) {
          p.born = t + Math.random() * 300;
          continue;
        }
        const travel = reduced ? 1 : ease(Math.min(1, age / 1300));
        const tx = barX(p.bar) + Math.sin(p.jitter) * 1.2;
        const a = amp(p.bar, reduced ? 0 : t);
        const ty = waveY + (p.frac - 0.5) * 2 * a;
        // arc upward out of the book
        const x = origin.x + (tx - origin.x) * travel;
        const y = origin.y + (ty - origin.y) * travel - Math.sin(travel * Math.PI) * H * 0.08;
        const fade = flowRef.current ? Math.min(1, (p.life - age) / 500) : 1;
        const alpha = Math.max(0, Math.min(1, age / 250)) * fade;
        ctx.beginPath();
        ctx.fillStyle = color(x, 0.9 * alpha);
        ctx.shadowColor = color(x, 0.9);
        ctx.shadowBlur = 8;
        ctx.arc(x, y, travel > 0.98 ? 1.6 : 1.2, 0, Math.PI * 2);
        ctx.fill();
        age = 0;
      }
      ctx.shadowBlur = 0;
      if (!reduced || t < 100) raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [size]);

  const w = size * 0.52;
  const h = size * 0.34;
  return (
    <div className={cn("relative select-none", className)} style={{ width: size * 1.5, height: size }} role="img" aria-label={label ?? `${brand.name}: a book opening into sound`}>
      <canvas ref={canvas} className="pointer-events-none absolute inset-0 z-10" style={{ width: size * 1.5, height: size }} aria-hidden />
      <div className="absolute left-1/2 -translate-x-1/2 [perspective:900px]" style={{ top: size * 0.56, width: w * 2, height: h }} aria-hidden>
        <div className="relative size-full [transform-style:preserve-3d] [transform:rotateX(52deg)]">
          {/* covers (underneath) */}
          <div className="absolute inset-y-[-3%] left-[-2%] w-[52%] rounded-l-xl bg-gradient-to-br from-[#2a1152] to-[#15161f] shadow-[0_0_0_1px_rgb(196_92_255/0.45),0_30px_50px_-10px_rgb(0_0_0/0.8)] [transform-origin:right] animate-[vx-open-left_1s_var(--ease-out-soft)_both]" />
          <div className="absolute inset-y-[-3%] right-[-2%] w-[52%] rounded-r-xl bg-gradient-to-bl from-[#2a1152] to-[#15161f] shadow-[0_0_0_1px_rgb(95_255_210/0.4),0_30px_50px_-10px_rgb(0_0_0/0.8)] [transform-origin:left] animate-[vx-open-right_1s_var(--ease-out-soft)_both]" />
          {/* page stack, lit from the spine */}
          {[0, 1, 2].map((i) => (
            <div key={i} className="absolute inset-0 [transform-style:preserve-3d]" style={{ transform: `translateZ(${(i + 1) * 1.5}px)` }}>
              <div
                className="absolute inset-y-[2%] left-[1%] w-[49%] rounded-l-lg bg-gradient-to-l from-[#f2ede4] via-[#d8d1c4] to-[#a9a293] [transform-origin:right] animate-[vx-open-left_1.05s_var(--ease-out-soft)_both]"
                style={{ animationDelay: `${0.08 * i}s`, opacity: 0.55 + i * 0.2 }}
              />
              <div
                className="absolute inset-y-[2%] right-[1%] w-[49%] rounded-r-lg bg-gradient-to-r from-[#f2ede4] via-[#d8d1c4] to-[#a9a293] [transform-origin:left] animate-[vx-open-right_1.05s_var(--ease-out-soft)_both]"
                style={{ animationDelay: `${0.08 * i}s`, opacity: 0.55 + i * 0.2 }}
              />
            </div>
          ))}
          <div className="absolute inset-y-[2%] left-1/2 w-[2px] -translate-x-1/2 bg-gradient-to-b from-orchid-400/60 via-[#f2ede4] to-mint-400/60 blur-[1px] [transform:translateZ(7px)]" />
        </div>
      </div>
    </div>
  );
}
