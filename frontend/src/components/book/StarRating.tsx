import { Star } from "lucide-react";
import type { BookRatings } from "@/types/api";
import { cn } from "@/utils/format";

/** Five stars filled to the average (partial stars included). */
export function Stars({ value, className }: { value: number; className?: string }) {
  return (
    <span className={cn("relative inline-flex shrink-0", className)} role="img" aria-label={`${value.toFixed(1)} out of 5 stars`}>
      <span className="flex gap-0.5 text-white/[0.18]">
        {Array.from({ length: 5 }, (_, i) => (
          <Star key={i} className="size-[1em] fill-current" aria-hidden />
        ))}
      </span>
      <span className="absolute inset-y-0 left-0 flex gap-0.5 overflow-hidden text-amber-400" style={{ width: `${(Math.max(0, Math.min(5, value)) / 5) * 100}%` }}>
        {Array.from({ length: 5 }, (_, i) => (
          <Star key={i} className="size-[1em] shrink-0 fill-current" aria-hidden />
        ))}
      </span>
    </span>
  );
}

/** "★★★★☆ 4.05 · 215 ratings · Open Library", or a quiet note when there are none. */
export function RatingLine({ ratings, size = "md", className }: { ratings: BookRatings | null | undefined; size?: "sm" | "md"; className?: string }) {
  if (!ratings || ratings.average == null || !ratings.count) {
    return <span className={cn("text-paper-500", size === "sm" ? "text-[11px]" : "text-xs", className)}>No reader ratings found</span>;
  }
  const count = `${ratings.count.toLocaleString()} rating${ratings.count === 1 ? "" : "s"}`;
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-x-2 gap-y-0.5", size === "sm" ? "text-[11px]" : "text-sm", className)}>
      <Stars value={ratings.average} className={size === "sm" ? "text-[11px]" : "text-[15px]"} />
      <span className="font-semibold text-paper-50 tabular-nums">{ratings.average.toFixed(2)}</span>
      <span className="text-paper-400">
        {count} ·{" "}
        {ratings.url ? (
          <a href={ratings.url} target="_blank" rel="noreferrer" className="underline decoration-white/20 underline-offset-2 hover:text-paper-100" onClick={(e) => e.stopPropagation()}>
            {ratings.source}
          </a>
        ) : (
          ratings.source
        )}
      </span>
    </span>
  );
}
