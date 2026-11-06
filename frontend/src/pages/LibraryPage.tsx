import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { BookPlus, Library, Play, Search } from "lucide-react";
import { ShelfCard } from "@/components/book/ShelfCard";
import { StatusBadge } from "@/components/book/StatusBadge";
import { bookHref } from "@/components/book/BookCard";
import { LayoutGrid, List } from "lucide-react";
import { BookCover } from "@/components/book/BookCover";
import { Button, ButtonLink } from "@/components/ui/Button";
import { EmptyState, Notice, ProgressBar, Skeleton } from "@/components/ui/Feedback";
import { Input, Segmented, Select } from "@/components/ui/Form";
import { booksApi } from "@/services/api";
import { errorMessage } from "@/services/http";
import { qk } from "@/services/queryClient";
import { useAuth } from "@/stores/auth";
import { usePlayer } from "@/stores/player";
import type { Book } from "@/types/api";
import { bookFraction, formatClock, formatDuration } from "@/utils/format";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { brand } from "@/config/brand";

const FILTERS = [
  { value: "all", label: "All" },
  { value: "in_progress", label: "Listening" },
  { value: "ready", label: "Ready" },
  { value: "processing", label: "Narrating" },
  { value: "review", label: "Draft" },
  { value: "completed", label: "Finished" },
];

const SORTS = [
  { value: "recent", label: "Recently added" },
  { value: "listened", label: "Recently played" },
  { value: "title", label: "Title" },
  { value: "author", label: "Author" },
  { value: "progress", label: "Progress" },
];

const GROUPS = [
  { value: "none", label: "No grouping" },
  { value: "series", label: "Group by series" },
  { value: "author", label: "Group by author" },
  { value: "genre", label: "Group by genre" },
];

type Group = { key: string; title: string; subtitle?: string; books: Book[] };

const bySeries = (a: Book, b: Book) =>
  (a.series ?? "~").localeCompare(b.series ?? "~") || (a.series_index ?? 0) - (b.series_index ?? 0) || a.title.localeCompare(b.title);

/** Sections for the chosen grouping; series always read in order. */
function groupBooks(books: Book[], mode: string): Group[] {
  const buckets = new Map<string, Book[]>();
  const add = (key: string, b: Book) => buckets.set(key, [...(buckets.get(key) ?? []), b]);
  if (mode === "series") {
    books.forEach((b) => add(b.series ? `${b.series}\u0000${b.author ?? ""}` : "￿", b));
    return [...buckets.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, items]) => {
        const [name, author] = key.split("\u0000");
        return key === "￿"
          ? { key, title: "Standalone novels", books: items.sort((a, b) => a.title.localeCompare(b.title)) }
          : { key, title: name, subtitle: `${author || "Unknown author"} · ${items.length} ${items.length === 1 ? "book" : "books"}`, books: items.sort(bySeries) };
      });
  }
  if (mode === "author") {
    books.forEach((b) => add(b.author || "Unknown author", b));
    return [...buckets.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, items]) => ({ key, title: key, subtitle: `${items.length} ${items.length === 1 ? "book" : "books"}`, books: items.sort(bySeries) }));
  }
  books.forEach((b) => add(b.genre || "Uncategorized", b));
  return [...buckets.entries()]
    .sort(([a, x], [b, y]) => (a === "Uncategorized" ? 1 : b === "Uncategorized" ? -1 : y.length - x.length || a.localeCompare(b)))
    .map(([key, items]) => ({ key, title: key, subtitle: `${items.length} ${items.length === 1 ? "book" : "books"}`, books: items.sort(bySeries) }));
}

function SeriesBadge({ book }: { book: Book }) {
  if (!book.series || book.series_index == null) return null;
  return (
    <span className="pointer-events-none absolute top-2 left-2 z-10 rounded-full bg-black/65 px-2 py-0.5 text-[11px] font-semibold text-[#f2ede4] backdrop-blur">
      Book {Number.isInteger(book.series_index) ? book.series_index : book.series_index.toFixed(1)}
    </span>
  );
}

function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export default function LibraryPage() {
  const [params, setParams] = useSearchParams();
  const status = params.get("filter") ?? "all";
  const sort = params.get("sort") ?? "recent";
  const group = params.get("group") ?? "none";
  const [q, setQ] = useState(params.get("q") ?? "");
  const [view, setView] = useState<"grid" | "list">(() => {
    try {
      return localStorage.getItem("vx.libraryView") === "list" ? "list" : "grid";
    } catch {
      return "grid";
    }
  });
  const query = useDebounced(q.trim());
  const user = useAuth((s) => s.user);
  useDocumentTitle("Library");

  const update = (key: string, value: string, fallback: string) => {
    const next = new URLSearchParams(params);
    if (value === fallback) next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
  };

  const books = useQuery({
    queryKey: qk.books({ status, sort, q: query }),
    queryFn: () => booksApi.list({ status, sort, q: query || undefined, limit: 200 }),
    refetchInterval: (qr) => (qr.state.data?.items.some((b) => b.status === "analyzing" || b.status === "generating") ? 4000 : false),
  });
  const cont = useQuery({ queryKey: qk.continue, queryFn: booksApi.continueListening });

  const hero = cont.data?.items[0];
  const firstRun = books.data && books.data.total === 0 && status === "all" && !query;

  return (
    <div className="space-y-10">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">{greeting()}{user ? `, ${user.display_name.split(" ")[0]}` : ""}</p>
          <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight text-paper-50">Your Library</h1>
          <p className="mt-1.5 text-sm text-paper-400">Every story, ready when you are.</p>
        </div>
        <ButtonLink to="/create" variant="primary" icon={<BookPlus className="size-4" />}>
          Create Audiobook
        </ButtonLink>
      </header>

      {hero && <ContinueHero book={hero} others={cont.data!.items.slice(1)} />}

      {firstRun ? (
        <EmptyState
          icon={<Library className="size-6" />}
          title="Your next story starts here."
          action={
            <ButtonLink to="/create" variant="primary" icon={<BookPlus className="size-4" />}>
              Create Audiobook
            </ButtonLink>
          }
        >
          Bring your first book into {brand.name} and turn it into an immersive listening experience.
        </EmptyState>
      ) : (
        <section aria-labelledby="all-books" className="space-y-6">
          <h2 id="all-books" className="sr-only">
            All books
          </h2>
          <div className="flex flex-wrap items-center gap-3">
            <Segmented label="Filter books" value={status} options={FILTERS} onChange={(v) => update("filter", v, "all")} />
            <div className="relative min-w-52 flex-1 sm:max-w-xs">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-paper-500" aria-hidden />
              <Input
                type="search"
                placeholder="Search titles and authors"
                aria-label="Search library"
                className="pl-9"
                value={q}
                onChange={(e) => {
                  setQ(e.target.value);
                  update("q", e.target.value, "");
                }}
              />
            </div>
            <Segmented
              label="View"
              value={view}
              onChange={(v) => {
                setView(v);
                try {
                  localStorage.setItem("vx.libraryView", v);
                } catch {
                  /* ignore */
                }
              }}
              options={[
                { value: "grid", label: <LayoutGrid className="size-4" aria-label="Grid" /> },
                { value: "list", label: <List className="size-4" aria-label="List" /> },
              ]}
            />
            <div className="ml-auto w-44">
              <Select aria-label="Group books" value={group} onChange={(e) => update("group", e.target.value, "none")}>
                {GROUPS.map((g) => (
                  <option key={g.value} value={g.value}>
                    {g.label}
                  </option>
                ))}
              </Select>
            </div>
            <div className="w-44">
              <Select aria-label="Sort books" value={sort} onChange={(e) => update("sort", e.target.value, "recent")}>
                {SORTS.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          {books.isError ? (
            <Notice kind="error" title="Couldn't load your library" action={<Button size="sm" onClick={() => void books.refetch()}>Retry</Button>}>
              {errorMessage(books.error)}
            </Notice>
          ) : books.isPending ? (
            <Grid>
              {Array.from({ length: 6 }, (_, i) => (
                <div key={i}>
                  <Skeleton className="aspect-[2/3]" />
                  <Skeleton className="mt-3 h-4 w-3/4" />
                  <Skeleton className="mt-2 h-3 w-1/2" />
                </div>
              ))}
            </Grid>
          ) : books.data.items.length === 0 ? (
            <p className="py-16 text-center text-sm text-paper-400">No books match{query ? ` "${query}"` : " this filter"}.</p>
          ) : group !== "none" ? (
            <div className="space-y-12">
              {groupBooks(books.data.items, group).map((g) => (
                <section key={g.key} aria-label={g.title} className="space-y-5">
                  <div className="flex items-baseline gap-3 border-b border-white/[0.06] pb-2">
                    <h3 className="font-display text-xl text-paper-50">{g.title}</h3>
                    {g.subtitle && <span className="text-sm text-paper-400">{g.subtitle}</span>}
                  </div>
                  <Grid>
                    {g.books.map((b) => (
                      <div key={b.id} className="relative">
                        <SeriesBadge book={b} />
                        <ShelfCard book={b} />
                      </div>
                    ))}
                  </Grid>
                </section>
              ))}
            </div>
          ) : view === "list" ? (
            <ul className="surface divide-y divide-white/[0.05] p-2">
              {books.data.items.map((b) => (
                <li key={b.id}>
                  <Link to={bookHref(b)} className="flex items-center gap-4 rounded-xl p-2.5 hover:bg-white/[0.04]">
                    <BookCover url={b.cover_url} title={b.title} size="sm" className="w-10 shrink-0" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-paper-50">{b.title}</p>
                      <p className="truncate text-xs text-paper-400">{b.author || "Unknown author"}</p>
                    </div>
                    <div className="hidden w-40 sm:block">
                      {bookFraction(b.progress?.book_position_seconds, b.total_duration) > 0 && <ProgressBar value={bookFraction(b.progress?.book_position_seconds, b.total_duration) * 100} className="h-1" label="Progress" />}
                    </div>
                    <span className="hidden w-20 text-right text-xs text-paper-500 md:block">{b.total_duration ? formatDuration(b.total_duration) : ""}</span>
                    <StatusBadge status={b.status} paused={b.active_job?.status === "paused"} />
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <Grid>
              {books.data.items.map((b) => (
                <ShelfCard key={b.id} book={b} />
              ))}
            </Grid>
          )}
        </section>
      )}
    </div>
  );
}

function Grid({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-2 gap-x-5 gap-y-9 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6">{children}</div>;
}

function greeting() {
  const h = new Date().getHours();
  return h < 5 ? "Late night listening" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

function ContinueHero({ book, others }: { book: Book; others: Book[] }) {
  const load = usePlayer((s) => s.load);
  const current = usePlayer((s) => s.bookId);
  const fraction = bookFraction(book.progress?.book_position_seconds, book.total_duration);
  return (
    <section aria-labelledby="continue" className="grid gap-4 lg:grid-cols-[2fr_1fr]">
      <div className="surface relative flex animate-fade-up items-center gap-5 overflow-hidden p-5 sm:gap-7 sm:p-7">
        {book.cover_url && (
          <img src={book.cover_url} alt="" aria-hidden className="pointer-events-none absolute inset-0 size-full scale-125 object-cover opacity-[0.12] blur-3xl" />
        )}
        <BookCover url={book.cover_url} title={book.title} author={book.author} className="relative w-24 shrink-0 sm:w-32" />
        <div className="relative min-w-0 flex-1">
          <p id="continue" className="eyebrow text-orchid-400/90">
            Continue listening
          </p>
          <h2 className="mt-2 truncate font-display text-2xl text-paper-50 sm:text-3xl">{book.title}</h2>
          <p className="mt-1 truncate text-sm text-paper-400">
            {book.current_chapter?.title ?? "Chapter"} · {formatClock(Math.min(book.progress?.position_seconds ?? 0, book.current_chapter?.duration ?? Infinity))}
            {book.current_chapter?.duration ? ` / ${formatClock(book.current_chapter.duration)}` : ""}
          </p>
          <div className="mt-4 flex items-center gap-3">
            <ProgressBar value={fraction * 100} className="max-w-xs" label="Book progress" />
            <span className="text-xs text-paper-400 tabular-nums">{Math.round(fraction * 100)}%</span>
          </div>
          <div className="mt-5 flex flex-wrap gap-2">
            <Button
              variant="primary"
              icon={<Play className="size-4 fill-current" />}
              onClick={() => (current === book.id ? usePlayer.getState().play() : load(book.id, { autoplay: true }))}
            >
              {current === book.id ? "Resume" : "Yes, resume"}
            </Button>
            <ButtonLink to={`/books/${book.id}`} variant="ghost">
              Details
            </ButtonLink>
          </div>
        </div>
      </div>
      {others.length > 0 && (
        <div className="surface p-4">
          <p className="eyebrow px-2 pt-1 pb-2">Also in progress</p>
          <ul className="space-y-1">
            {others.slice(0, 4).map((b) => (
              <li key={b.id}>
                <Link to={`/books/${b.id}`} className="flex items-center gap-3 rounded-xl p-2 hover:bg-white/[0.04]">
                  <BookCover url={b.cover_url} title={b.title} size="sm" className="w-9 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-paper-100">{b.title}</p>
                    <ProgressBar value={bookFraction(b.progress?.book_position_seconds, b.total_duration) * 100} className="mt-1.5 h-1" label="Progress" />
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
