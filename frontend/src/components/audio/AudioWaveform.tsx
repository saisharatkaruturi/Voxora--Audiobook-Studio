import { useEffect, useRef } from "react";
import { brand } from "@/config/brand";
import { cn } from "@/utils/format";

export interface AudioWaveformProps {
  /** Animate at all (hover / playing / previewing / generating). */
  active?: boolean;
  /** Live level source 0..1 (e.g. `audioLevel` from the player); a deterministic simulation otherwise. */
  level?: () => number;
  bars?: number;
  className?: string;
  /** Resting height when inactive, 0..1. */
  rest?: number;
  gap?: number;
  label?: string;
}

/**
 * VOXORA's waveform: rounded bars with a purple -> mint gradient and organic,
 * layered motion. One canvas, no DOM per bar; the loop stops when inactive or hidden.
 */
export function AudioWaveform({ active = false, level, bars = 48, className, rest = 0.18, gap = 0.45, label }: AudioWaveformProps) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const state = useRef({ active, level, energy: 0 });
  state.current.active = active;
  state.current.level = level;

  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const ctx = el.getContext("2d");
    if (!ctx) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    let raf = 0;
    let visible = true;
    const io = new IntersectionObserver(([e]) => {
      visible = e.isIntersecting;
      if (visible) raf = requestAnimationFrame(draw);
    });
    io.observe(el);
    const heights = new Float32Array(bars).fill(rest);

    function draw(now: number) {
      if (!el || !ctx) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = el.clientWidth;
      const h = el.clientHeight;
      if (el.width !== Math.round(w * dpr)) {
        el.width = Math.round(w * dpr);
        el.height = Math.round(h * dpr);
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const s = state.current;
      const live = s.level ? s.level() : 0;
      const t = now / 1000;
      const target = s.active ? (s.level ? 0.25 + live * 0.9 : 0.55 + 0.25 * Math.sin(t * 1.3)) : 0;
      s.energy += (target - s.energy) * 0.08;
      const bw = w / (bars + (bars - 1) * gap);
      // The theme's one accent (teal), read live so it follows light / dark.
      ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--color-orchid-500").trim() || brand.colors.orchid;
      let settled = true;
      for (let i = 0; i < bars; i++) {
        const x = i / (bars - 1);
        const envelope = 0.35 + 0.65 * Math.sin(Math.PI * x);
        const organic = 0.5 + 0.5 * Math.sin(t * 3.1 + i * 0.55) * Math.cos(t * 1.7 + i * 0.23) + 0.18 * Math.sin(t * 7.3 + i * 1.9);
        const want = rest * envelope * 0.9 + s.energy * envelope * Math.max(0.12, organic);
        heights[i] += (Math.min(1, want) - heights[i]) * (reduced ? 1 : 0.22);
        if (Math.abs(heights[i] - want) > 0.004) settled = false;
        const bh = Math.max(bw, heights[i] * h);
        const bx = i * bw * (1 + gap);
        ctx.beginPath();
        ctx.roundRect(bx, (h - bh) / 2, bw, bh, bw / 2);
        ctx.fill();
      }
      if (visible && (s.active || !settled) && !reduced) raf = requestAnimationFrame(draw);
    }
    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      io.disconnect();
    };
    // restart the loop when activity changes
  }, [bars, rest, gap, active]);

  return <canvas ref={canvas} className={cn("block h-10 w-full", className)} role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true} />;
}

export const MiniWaveform = (p: Omit<AudioWaveformProps, "bars">) => <AudioWaveform bars={14} gap={0.6} rest={0.25} {...p} className={cn("h-5 w-14", p.className)} />;
export const VoiceWaveform = (p: Omit<AudioWaveformProps, "bars">) => <AudioWaveform bars={32} rest={0.32} {...p} className={cn("h-8", p.className)} />;
export const HeroWaveform = (p: Omit<AudioWaveformProps, "bars">) => <AudioWaveform bars={72} gap={0.5} rest={0.2} {...p} className={cn("h-16", p.className)} />;
