import { useEffect, useRef } from "react";
import { BookCover } from "@/components/book/BookCover";
import { audioLevel, usePlayer } from "@/stores/player";

/** The cover breathes and glows with the narration's actual loudness while playing. */
export function LivingCover({ url, title, author }: { url: string | null; title: string; author: string | null }) {
  const wrap = useRef<HTMLDivElement>(null);
  const glow = useRef<HTMLDivElement>(null);
  const playing = usePlayer((s) => s.playing);
  useEffect(() => {
    if (!playing || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let raf = 0;
    let smooth = 0;
    const tick = (now: number) => {
      const lvl = audioLevel();
      const target = lvl > 0 ? lvl : 0.35 + 0.15 * Math.sin(now / 600);
      smooth += (target - smooth) * 0.12;
      if (wrap.current) wrap.current.style.transform = `perspective(1000px) rotateY(${Math.sin(now / 3200) * 4}deg) rotateX(${Math.cos(now / 4100) * 2}deg) scale(${1 + smooth * 0.018})`;
      if (glow.current) glow.current.style.opacity = String(0.25 + smooth * 0.6);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      if (wrap.current) wrap.current.style.transform = "";
    };
  }, [playing]);
  return (
    <div className="relative mx-auto w-[min(58vw,260px)] lg:w-[min(240px,27vh)]">
      <div ref={glow} className="absolute -inset-8 -z-10 rounded-full bg-[radial-gradient(closest-side,rgb(196_92_255/0.45),rgb(95_255_210/0.12),transparent)] opacity-25 blur-2xl transition-opacity" aria-hidden />
      <div ref={wrap} className="transition-transform duration-700 ease-[var(--ease-out-soft)] will-change-transform">
        <BookCover url={url} title={title} author={author} size="lg" />
      </div>
    </div>
  );
}
