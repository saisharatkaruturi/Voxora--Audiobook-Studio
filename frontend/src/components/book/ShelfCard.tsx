import { useRef } from "react";
import { Link } from "react-router-dom";
import { Pause, Play } from "lucide-react";
import { BookCover } from "@/components/book/BookCover";
import { bookHref } from "@/components/book/BookCard";
import { MiniWaveform } from "@/components/audio/AudioWaveform";
import { StatusBadge } from "@/components/book/StatusBadge";
import { ProgressBar } from "@/components/ui/Feedback";
import { audioLevel, usePlayer } from "@/stores/player";
import type { Book } from "@/types/api";
import { bookFraction, cn, formatDuration } from "@/utils/format";

/** Premium book card with pointer-driven 3D tilt; play button when audio exists. */
export function ShelfCard({ book, className }: { book: Book; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const { bookId, playing, load, toggle } = usePlayer();
  const isCurrent = bookId === book.id;
  const ready = (book.chapters_with_audio ?? 0) > 0;
  const fraction = bookFraction(book.progress?.book_position_seconds, book.total_duration);
  const onMove = (e: React.PointerEvent) => {
    const el = ref.current;
    if (!el || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const r = el.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width - 0.5;
    const y = (e.clientY - r.top) / r.height - 0.5;
    el.style.transform = `perspective(900px) rotateY(${x * 10}deg) rotateX(${-y * 10}deg) translateY(-4px)`;
  };
  const reset = () => {
    if (ref.current) ref.current.style.transform = "";
  };
  return (
    <article className={cn("group relative", className)}>
      <div ref={ref} onPointerMove={onMove} onPointerLeave={reset} className="relative transition-transform duration-300 ease-[var(--ease-out-soft)] will-change-transform">
        <Link to={bookHref(book)} aria-label={`${book.title}${book.author ? ` by ${book.author}` : ""}`} className="block rounded-xl">
          <BookCover url={book.cover_url} title={book.title} author={book.author} />
        </Link>
        {ready && (
          <button
            type="button"
            onClick={() => (isCurrent ? toggle() : void load(book.id, { autoplay: true }))}
            aria-label={isCurrent && playing ? `Pause ${book.title}` : `Play ${book.title}`}
            className={cn(
              "neo absolute right-3 bottom-3 flex size-11 items-center justify-center rounded-full text-paper-50 transition-all duration-300",
              isCurrent && playing ? "opacity-100" : "translate-y-1 opacity-0 group-hover:translate-y-0 group-hover:opacity-100 focus-visible:translate-y-0 focus-visible:opacity-100 max-md:translate-y-0 max-md:opacity-100",
            )}
          >
            {isCurrent && playing ? <Pause className="size-4 fill-current" /> : <Play className="size-4 translate-x-px fill-current" />}
          </button>
        )}
      </div>
      <div className="mt-3 space-y-1 px-0.5">
        <h3 className="line-clamp-2 text-[15px] leading-snug font-medium text-paper-50">{book.title}</h3>
        <p className="truncate text-[13px] text-paper-400">{book.author || "Unknown author"}</p>
        {book.status !== "ready" ? (
          <div className="pt-0.5">
            <StatusBadge status={book.status} paused={book.active_job?.status === "paused"} />
          </div>
        ) : (
          <div className="flex items-center gap-2 text-xs text-paper-500">
            {isCurrent && playing ? <MiniWaveform active level={audioLevel} className="h-4 w-10" /> : null}
            {book.progress?.completed ? <span className="text-mint-400">Finished</span> : book.narrator && <span className="truncate">{book.narrator}</span>}
            {book.total_duration ? <span className="shrink-0">· {formatDuration(book.total_duration)}</span> : null}
          </div>
        )}
        {fraction > 0 && !book.progress?.completed && (
          <div className="flex items-center gap-2 pt-1">
            <ProgressBar value={fraction * 100} className="h-1" label="Listening progress" />
            <span className="text-[11px] text-paper-500 tabular-nums">{Math.round(fraction * 100)}%</span>
          </div>
        )}
        {book.status === "generating" && book.active_job && <ProgressBar value={book.active_job.progress} className="mt-1 h-1" label="Generation progress" />}
      </div>
    </article>
  );
}
