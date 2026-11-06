import { cn } from "@/utils/format";

/**
 * The VOXORA symbol: an open book page on the left that turns into a sound wave
 * on the right. BOOK → VOICE → SOUND, legible down to 16px.
 */
export function BrandMark({ className, tile = false, animated = false, title }: { className?: string; tile?: boolean; animated?: boolean; title?: string }) {
    const bars = [
    { x: 26, y: 16.5, h: 19 },
    { x: 31.5, y: 11.5, h: 29 },
    { x: 37, y: 18.5, h: 15 },
    { x: 42.5, y: 23, h: 6 },
  ];
  return (
    <svg viewBox="0 0 48 48" className={cn("size-8 text-orchid-500 [:root[data-theme=light]_&]:text-paper-100", className)} role={title ? "img" : undefined} aria-label={title} aria-hidden={title ? undefined : true}>
      {tile && <rect width="48" height="48" rx="12" fill="#0b3048" />}
      {/* the page */}
      <path d="M23 38c-5.2-3.4-11.3-4-17-2.1V13.2c5.7-1.9 11.8-1.3 17 2.1z" fill="currentColor" />
      <path d="M23 15.3v22.7" stroke="var(--page-bg)" strokeOpacity=".5" strokeWidth="1" />
      {/* the voice */}
      {bars.map((b, i) => (
        <rect
          key={i}
          x={b.x - 1.75}
          y={b.y}
          width="3.5"
          height={b.h}
          rx="1.75"
          fill="currentColor"
          className={animated ? "origin-center animate-[vx-bar_1.1s_ease-in-out_infinite]" : undefined}
          style={animated ? { animationDelay: `${i * 0.12}s`, transformBox: "fill-box" } : undefined}
        />
      ))}
    </svg>
  );
}
