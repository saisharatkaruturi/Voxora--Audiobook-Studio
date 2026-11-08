import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Sparkles } from "lucide-react";
import { RatingLine } from "@/components/book/StarRating";
import { Button } from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useJob } from "@/hooks/useJob";
import { booksApi } from "@/services/api";
import { errorMessage } from "@/services/http";
import { qk } from "@/services/queryClient";
import type { Book } from "@/types/api";

/**
 * Genre, what the book is about (AI, spoiler-free) and real reader ratings.
 * Filled in automatically after upload; "Refresh" looks it up again.
 */
export function AboutBook({ book }: { book: Book }) {
  const qc = useQueryClient();
  const [jobId, setJobId] = useState<string | null>(null);
  const refresh = () => void qc.invalidateQueries({ queryKey: qk.book(book.id) });
  const job = useJob(jobId, (j) => {
    setJobId(null);
    refresh();
    if (j.status === "failed") toast.error(j.error?.message ?? "Couldn't look this book up.");
  });
  const lookup = useMutation({
    mutationFn: () => booksApi.refreshInfo(book.id),
    onSuccess: (j) => setJobId(j.id),
    onError: (e) => toast.error(errorMessage(e)),
  });

  // Right after upload the lookup runs in the background: check back until it lands (up to ~3 minutes).
  const pending = !book.classified_at && book.status !== "failed";
  useEffect(() => {
    if (!pending) return;
    let n = 0;
    const t = setInterval(() => {
      if (++n > 36) clearInterval(t);
      refresh();
    }, 5000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending, book.id]);

  const working = lookup.isPending || !!jobId;
  const about = book.about ?? book.description;
  const genres = book.genres?.length ? book.genres : book.genre ? [book.genre] : [];

  return (
    <section className="surface p-6 sm:p-8" aria-labelledby="about-book">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="about-book" className="font-display text-xl text-paper-50">
            About this book
          </h2>
          {genres.length > 0 && <p className="mt-1 text-sm text-orchid-300">{genres.join(" · ")}</p>}
        </div>
        <Button size="sm" variant="ghost" icon={<RefreshCw className={working ? "size-3.5 animate-spin" : "size-3.5"} />} onClick={() => lookup.mutate()} disabled={working}>
          {working ? (job?.message ? "Looking up…" : "Starting…") : book.classified_at ? "Refresh" : "Look up now"}
        </Button>
      </div>

      {pending && !about ? (
        <div className="mt-5 flex items-center gap-3 text-sm text-paper-400">
          <Sparkles className="size-4 animate-pulse-soft text-orchid-400" />
          Finding the genre, what this book is about and its reader ratings…
        </div>
      ) : (
        <>
          <div className="mt-4">{book.classified_at || book.ratings ? <RatingLine ratings={book.ratings} /> : null}</div>
          {about ? (
            <p className="mt-4 max-w-3xl leading-relaxed text-paper-200">{about}</p>
          ) : (
            <p className="mt-4 text-sm text-paper-500">No description yet. Use “Look up now” to have the AI read the opening and describe it.</p>
          )}
          {book.about && <p className="mt-4 text-[11px] text-paper-500">Description written by AI from the book · ratings from Open Library readers</p>}
        </>
      )}
    </section>
  );
}
