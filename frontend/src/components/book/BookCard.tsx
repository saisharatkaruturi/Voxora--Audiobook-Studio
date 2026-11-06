import { Link } from "react-router-dom";
import { Play } from "lucide-react";
import { BookCover } from "@/components/book/BookCover";
import { StatusBadge } from "@/components/book/StatusBadge";
import { ProgressBar } from "@/components/ui/Feedback";
import { usePlayer } from "@/stores/player";
import type { Book } from "@/types/api";
import { bookFraction, formatDuration } from "@/utils/format";

export function bookHref(book: Pick<Book, "id" | "status">): string {
  if (book.status === "analyzing" || book.status === "uploaded" || book.status === "failed") return `/books/${book.id}/processing`;
  if (book.status === "review") return `/books/${book.id}/edit`;
  if (book.status === "generating") return `/books/${book.id}/processing`;
  return `/books/${book.id}`;
}

export function BookCard({ book }: { book: Book }) {
  const fraction = bookFraction(book.progress?.book_position_seconds, book.total_duration);
  const load = usePlayer((s) => s.load);
  const paused = book.active_job?.status === "paused";
  const done = book.progress?.completed;
  return (
    <article className="group relative animate-fade-up">
      <Link to={bookHref(book)} className="block rounded-xl focus-visible:outline-offset-4" aria-label={`${book.title}${book.author ? ` by ${book.author}` : ""}`}>
        <div className="relative transition-transform duration-300 ease-[var(--ease-out-soft)] group-hover:-translate-y-1">
          <BookCover url={book.cover_url} title={book.title} author={book.author} />
          {book.status === "generating" && book.active_job && (
            <div className="absolute inset-x-2 bottom-2 rounded-lg bg-black/60 px-2 py-1.5 text-[#f2ede4] backdrop-blur">
              <ProgressBar value={book.active_job.progress} label="Generation progress" />
            </div>
          )}
        </div>
      </Link>
      {book.status === "ready" && (
        <button
          type="button"
          onClick={() => void load(book.id, { autoplay: true })}
          className="absolute top-[calc(66%)] right-3 flex size-11 translate-y-2 items-center justify-center rounded-full bg-paper-100 text-ink-950 opacity-0 shadow-xl transition-all duration-300 group-hover:translate-y-0 group-hover:opacity-100 focus-visible:translate-y-0 focus-visible:opacity-100 max-md:hidden"
          aria-label={`Play ${book.title}`}
        >
          <Play className="size-5 translate-x-px fill-current" />
        </button>
      )}
      <div className="mt-3 space-y-1.5 px-0.5">
        <h3 className="line-clamp-2 text-[15px] leading-snug font-medium text-paper-50">{book.title}</h3>
        <p className="truncate text-[13px] text-paper-400">{book.author || "Unknown author"}</p>
        <div className="flex flex-wrap items-center gap-2 pt-0.5">
          {book.status !== "ready" ? (
            <StatusBadge status={book.status} paused={paused} />
          ) : done ? (
            <span className="text-xs text-sage-400">Finished</span>
          ) : (
            <span className="text-xs text-paper-500">{formatDuration(book.total_duration)}</span>
          )}
        </div>
        {fraction > 0 && !done && (
          <div className="flex items-center gap-2 pt-1">
            <ProgressBar value={fraction * 100} className="h-1" label="Listening progress" />
            <span className="text-[11px] text-paper-500 tabular-nums">{Math.round(fraction * 100)}%</span>
          </div>
        )}
      </div>
    </article>
  );
}
