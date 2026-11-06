import { useState } from "react";
import { cn } from "@/utils/format";

const PALETTES = [
  ["#3b2a1f", "#8a5a34"],
  ["#1f2a3b", "#3f6a8a"],
  ["#2a3b1f", "#5e8a3f"],
  ["#3b1f2e", "#8a3f63"],
  ["#2e2a24", "#7a6a52"],
];

function hash(s: string) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

/** A book cover image, with a typographic fallback when no image exists or it fails to load. */
export function BookCover({
  url,
  title,
  author,
  className,
  size = "md",
}: {
  url: string | null | undefined;
  title: string;
  author?: string | null;
  className?: string;
  size?: "sm" | "md" | "lg";
}) {
  const [failed, setFailed] = useState(false);
  const [a, b] = PALETTES[hash(title) % PALETTES.length];
  return (
    <div
      className={cn("relative aspect-[2/3] overflow-hidden rounded-xl bg-ink-800 shadow-[var(--shadow-cover)]", size === "sm" && "rounded-lg", className)}
    >
      {url && !failed ? (
        <img src={url} alt={`Cover of ${title}`} className="size-full object-cover" loading="lazy" decoding="async" onError={() => setFailed(true)} />
      ) : (
        <div className="flex size-full flex-col justify-between p-[9%]" style={{ background: `linear-gradient(160deg, ${a}, ${b})` }} role="img" aria-label={`Cover of ${title}`}>
          <div className="h-px w-1/3 bg-[rgb(255_255_255/0.4)]" />
          <div>
            <p className={cn("font-serif leading-tight text-[rgb(255_255_255/0.95)]", size === "sm" ? "text-[11px]" : size === "lg" ? "text-2xl" : "text-base")}>{title}</p>
            {author && size !== "sm" && <p className="mt-2 text-[11px] tracking-wide text-[rgb(255_255_255/0.7)] uppercase">{author}</p>}
          </div>
        </div>
      )}
      <div className="pointer-events-none absolute inset-0 rounded-[inherit] bg-gradient-to-r from-black/25 via-transparent to-transparent" style={{ maskImage: "linear-gradient(90deg, black 0 6%, transparent 9%)" }} />
    </div>
  );
}
