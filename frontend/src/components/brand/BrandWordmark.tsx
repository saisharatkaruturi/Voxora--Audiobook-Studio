import { Link } from "react-router-dom";
import { brand } from "@/config/brand";
import { BrandMark } from "@/components/brand/BrandMark";
import { cn } from "@/utils/format";

/** "VOXORA" set in the display face with wide tracking; the first O carries a tiny living waveform. */
export function BrandWordmark({ className, size = "md", live = true }: { className?: string; size?: "sm" | "md" | "lg" | "xl"; live?: boolean }) {
  const text = { sm: "text-[15px]", md: "text-[18px]", lg: "text-3xl", xl: "text-5xl sm:text-6xl" }[size];
  return (
    <span className={cn("inline-flex items-center font-display font-semibold tracking-[0.2em] text-paper-50", text, className)} aria-label={brand.name} role="img">
      <span aria-hidden>V</span>
      <span aria-hidden className="relative mx-[0.02em] inline-flex h-[0.74em] w-[0.74em] items-center justify-center rounded-full border-[0.1em] border-current">
        <span className="flex h-[0.34em] items-center gap-[0.05em]">
          {[0.55, 1, 0.7].map((h, i) => (
            <span
              key={i}
              className={cn("block w-[0.07em] rounded-full bg-orchid-500 [:root[data-theme=light]_&]:bg-paper-100", live && "animate-[vx-bar_1.2s_ease-in-out_infinite]")}
              style={{ height: `${h * 100}%`, animationDelay: `${i * 0.15}s` }}
            />
          ))}
        </span>
      </span>
      <span aria-hidden className="ml-[0.18em]">XORA</span>
    </span>
  );
}

/** Mark + wordmark, linking home. The one way the product name appears in chrome. */
export function Logo({ to = "/library", compact = false, className }: { to?: string; compact?: boolean; className?: string }) {
  return (
    <Link to={to} className={cn("inline-flex items-center gap-2.5 rounded-lg", className)} aria-label={`${brand.name} home`}>
      <BrandMark className={compact ? "size-7" : "size-8"} />
      <BrandWordmark size={compact ? "sm" : "md"} />
    </Link>
  );
}

/** Small "VOXORA" chip for brand touchpoints (player, book details). */
export function BrandBadge({ className, label }: { className?: string; label?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full border border-white/[0.08] bg-white/[0.03] py-1 pr-2.5 pl-1.5 text-[10px] font-semibold tracking-[0.22em] text-paper-300", className)}>
      <BrandMark className="size-4" />
      {label ?? brand.name}
    </span>
  );
}
