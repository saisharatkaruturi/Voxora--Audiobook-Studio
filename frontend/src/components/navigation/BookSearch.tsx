import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, BookOpen, Library, Search, Sparkles } from "lucide-react";
import { BrandMark } from "@/components/brand/BrandMark";
import { RatingLine } from "@/components/book/StarRating";
import { systemApi } from "@/services/api";
import { errorMessage } from "@/services/http";
import type { FoundBook } from "@/types/api";
import { cn } from "@/utils/format";

function useDebounced(value: string, ms: number) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/**
 * The search palette. Your library answers instantly; the book finder (AI + Open
 * Library ratings) answers any title, author or character a moment later with what
 * the book is about, its ratings and what to read next.
 */
export function BookSearch({ onClose }: { onClose: () => void }) {
  const [q, setQ] = useState("");
  const quick = useDebounced(q.trim(), 180);
  const slow = useDebounced(q.trim(), 900);
  const navigate = useNavigate();

  const library = useQuery({ queryKey: ["search", quick], queryFn: () => systemApi.search(quick), enabled: quick.length > 1 });
  const finder = useQuery({
    queryKey: ["book-finder", slow.toLowerCase()],
    queryFn: () => systemApi.findBooks(slow),
    enabled: slow.length > 2,
    staleTime: 60 * 60 * 1000,
    retry: false,
  });

  const go = (to: string) => {
    onClose();
    navigate(to);
  };
  useEffect(() => {
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [onClose]);

  const results = [
    ...(library.data?.books ?? []).map((b) => ({ key: `b${b.id}`, to: `/books/${b.id}`, title: b.title, sub: b.author ?? "Book" })),
    ...(library.data?.chapters ?? []).map((c) => ({ key: `c${c.id}`, to: `/books/${c.book_id}/edit`, title: c.title, sub: c.book_title })),
  ];
  const typing = q.trim() !== slow;
  const data = finder.data && !typing ? finder.data : null;

  return (
    <div className="fixed inset-0 z-[80] flex items-start justify-center bg-black/50 px-4 pt-[8vh] backdrop-blur-sm" onMouseDown={onClose} role="dialog" aria-modal="true" aria-label="Search">
      <div className="glass flex max-h-[84vh] w-full max-w-2xl animate-fade-up flex-col overflow-hidden rounded-3xl shadow-2xl" onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex shrink-0 items-center gap-3 border-b border-white/[0.06] px-5">
          <Search className="size-4 text-paper-500" />
          <input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && results[0] && go(results[0].to)}
            placeholder="Search a book, author or character"
            aria-label="Search a book, author or character"
            className="h-14 flex-1 bg-transparent text-[15px] text-paper-50 placeholder:text-paper-500 focus:outline-none"
          />
          <kbd className="rounded-md border border-white/10 px-1.5 py-0.5 text-[10px] text-paper-500">Esc</kbd>
        </div>

        <div className="overflow-y-auto p-2">
          {quick.length < 2 ? (
            <div className="flex items-start gap-3 px-3 py-6 text-sm text-paper-400">
              <BrandMark className="size-5 shrink-0" />
              <div>
                <p className="text-paper-200">Search your library, or any book in the world.</p>
                <p className="mt-1 text-paper-500">Try a title (“The Silent Patient”), an author (“Colleen Hoover”) or a character (“Hermione”).</p>
              </div>
            </div>
          ) : (
            <>
              {results.length > 0 && (
                <Section icon={<Library className="size-3.5" />} title="In your library">
                  <ul>
                    {results.map((r) => (
                      <li key={r.key}>
                        <button type="button" onClick={() => go(r.to)} className="flex w-full flex-col rounded-xl px-3 py-2.5 text-left hover:bg-white/[0.06] focus-visible:bg-white/[0.06]">
                          <span className="text-sm text-paper-50">{r.title}</span>
                          <span className="text-xs text-paper-500">{r.sub}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </Section>
              )}

              {q.trim().length > 2 && (
                <Section icon={<Sparkles className="size-3.5" />} title="Book finder">
                  {typing || finder.isFetching ? (
                    <FinderLoading query={q.trim()} />
                  ) : finder.isError ? (
                    <p className="px-3 py-4 text-sm text-rose-400">{errorMessage(finder.error)}</p>
                  ) : data ? (
                    <div className="space-y-4 px-1 pb-2">
                      {data.interpretation && <p className="px-2 text-xs text-paper-400">{data.interpretation}</p>}
                      {data.matches.length === 0 ? (
                        <p className="px-2 text-sm text-paper-500">No published book matches “{data.query}”.</p>
                      ) : (
                        data.matches.map((b) => <MatchCard key={b.title} book={b} onOpen={go} />)
                      )}
                      {data.recommendations.length > 0 && (
                        <div>
                          <p className="px-2 pb-2 text-[11px] font-semibold tracking-wide text-paper-500 uppercase">You might also like</p>
                          <ul className="grid gap-1">
                            {data.recommendations.map((b) => (
                              <li key={b.title}>
                                <RecommendationRow book={b} onSearch={() => setQ(b.title)} onOpen={go} />
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      <p className="px-2 text-[10px] text-paper-500">Descriptions and picks by AI · ratings from Open Library readers</p>
                    </div>
                  ) : null}
                </Section>
              )}

              {results.length === 0 && q.trim().length <= 2 && !library.isPending && (
                <p className="px-3 py-6 text-sm text-paper-500">No books or chapters match “{quick}”.</p>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Section({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <section className="mb-2">
      <h3 className="flex items-center gap-1.5 px-3 pt-2 pb-1.5 text-[11px] font-semibold tracking-wide text-orchid-300 uppercase">
        {icon}
        {title}
      </h3>
      {children}
    </section>
  );
}

function FinderLoading({ query }: { query: string }) {
  return (
    <div className="px-3 pb-3">
      <p className="flex items-center gap-2 py-2 text-sm text-paper-400">
        <span className="flex h-4 items-end gap-0.5" aria-hidden>
          {[0, 1, 2, 3].map((i) => (
            <span key={i} className="w-0.5 rounded-full bg-orchid-400 animate-[vx-bar_1s_ease-in-out_infinite]" style={{ height: "100%", animationDelay: `${i * 0.12}s` }} />
          ))}
        </span>
        Looking up “{query}”… this takes a few seconds.
      </p>
      <div className="mt-2 flex gap-4">
        <div className="h-28 w-20 animate-pulse-soft rounded-lg bg-white/[0.06]" />
        <div className="flex-1 space-y-2 pt-1">
          <div className="h-4 w-2/3 animate-pulse-soft rounded bg-white/[0.06]" />
          <div className="h-3 w-1/3 animate-pulse-soft rounded bg-white/[0.06]" />
          <div className="h-3 w-full animate-pulse-soft rounded bg-white/[0.06]" />
          <div className="h-3 w-5/6 animate-pulse-soft rounded bg-white/[0.06]" />
        </div>
      </div>
    </div>
  );
}

function Cover({ book, className }: { book: FoundBook; className?: string }) {
  const [broken, setBroken] = useState(false);
  return book.cover_url && !broken ? (
    <img src={book.cover_url} alt="" loading="lazy" onError={() => setBroken(true)} className={cn("shrink-0 rounded-md object-cover shadow-[var(--shadow-cover)]", className)} />
  ) : (
    <div className={cn("flex shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-plum-800 to-ink-700 text-orchid-300", className)} aria-hidden>
      <BookOpen className="size-5" />
    </div>
  );
}

function byline(b: FoundBook) {
  return [b.author, b.year].filter(Boolean).join(" · ");
}

function MatchCard({ book, onOpen }: { book: FoundBook; onOpen: (to: string) => void }) {
  return (
    <article className="flex gap-4 rounded-2xl bg-white/[0.04] p-3 sm:p-4">
      <Cover book={book} className="h-32 w-[5.5rem]" />
      <div className="min-w-0 flex-1">
        <h4 className="font-display text-lg leading-snug text-paper-50">{book.title}</h4>
        {byline(book) && <p className="text-sm text-paper-400">{byline(book)}</p>}
        <RatingLine ratings={book.ratings} className="mt-2" />
        {book.genres.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {book.genres.map((g) => (
              <span key={g} className="rounded-full bg-orchid-500/10 px-2.5 py-0.5 text-[11px] text-orchid-300">
                {g}
              </span>
            ))}
          </div>
        )}
        {book.match_note && book.matched_on !== "title" && <p className="mt-2 text-xs text-mint-400">{book.match_note}</p>}
        {book.about && <p className="mt-2 text-sm leading-relaxed text-paper-200">{book.about}</p>}
        {book.library_book_id && (
          <button type="button" onClick={() => onOpen(`/books/${book.library_book_id}`)} className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-orchid-300 hover:text-orchid-200">
            Open in your library <ArrowRight className="size-3.5" />
          </button>
        )}
      </div>
    </article>
  );
}

function RecommendationRow({ book, onSearch, onOpen }: { book: FoundBook; onSearch: () => void; onOpen: (to: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => (book.library_book_id ? onOpen(`/books/${book.library_book_id}`) : onSearch())}
      title={book.library_book_id ? "Open in your library" : `Search for ${book.title}`}
      className="flex w-full gap-3 rounded-xl px-2 py-2 text-left hover:bg-white/[0.05] focus-visible:bg-white/[0.05]"
    >
      <Cover book={book} className="h-16 w-11" />
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-sm font-medium text-paper-50">{book.title}</span>
          <span className="text-xs text-paper-500">{byline(book)}</span>
          {book.library_book_id && <span className="text-[10px] text-mint-400">In your library</span>}
        </span>
        <RatingLine ratings={book.ratings} size="sm" className="mt-0.5" />
        {book.why && <span className="mt-0.5 line-clamp-2 block text-xs text-paper-400">{book.why}</span>}
      </span>
    </button>
  );
}
