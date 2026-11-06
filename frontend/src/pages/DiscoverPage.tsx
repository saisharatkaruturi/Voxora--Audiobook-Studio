import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Headphones, Hourglass, Mic2, Users, type LucideIcon } from "lucide-react";
import { BookCover } from "@/components/book/BookCover";
import { ShelfCard } from "@/components/book/ShelfCard";
import { ButtonLink } from "@/components/ui/Button";
import { EmptyState, PageLoader } from "@/components/ui/Feedback";
import { BrandMark } from "@/components/brand/BrandMark";
import { reveal, stagger } from "@/config/motion";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { booksApi } from "@/services/api";
import { qk } from "@/services/queryClient";
import type { Book } from "@/types/api";
import { cn } from "@/utils/format";

interface Collection {
  key: string;
  title: string;
  blurb: string;
  icon: LucideIcon;
  gradient: string;
  books: Book[];
}

/** Smart collections, computed from your own library. */
function collections(books: Book[]): Collection[] {
  const ready = books.filter((b) => (b.chapters_with_audio ?? 0) > 0);
  return [
    {
      key: "continue",
      title: "Pick up where you left off",
      blurb: "Stories you've started and not finished.",
      icon: Headphones,
      gradient: "from-orchid-500/25 via-plum-800/40 to-transparent",
      books: ready.filter((b) => b.progress && !b.progress.completed && b.progress.book_position_seconds > 1),
    },
    {
      key: "short",
      title: "Under six hours",
      blurb: "Finish in a weekend, or an evening.",
      icon: Hourglass,
      gradient: "from-mint-500/20 via-plum-800/40 to-transparent",
      books: ready.filter((b) => (b.total_duration ?? Infinity) < 6 * 3600),
    },
    {
      key: "cast",
      title: "Full cast",
      blurb: "Narrated with a voice for every character.",
      icon: Users,
      gradient: "from-amber-400/20 via-plum-800/40 to-transparent",
      books: ready.filter((b) => b.narration?.cast_mode),
    },
    {
      key: "draft",
      title: "Ready for a voice",
      blurb: "Read and structured, waiting for a narrator.",
      icon: Mic2,
      gradient: "from-sky-400/20 via-plum-800/40 to-transparent",
      books: books.filter((b) => b.status === "review"),
    },
  ];
}

export default function DiscoverPage() {
  useDocumentTitle("Discover");
  const q = useQuery({ queryKey: qk.books({ discover: true }), queryFn: () => booksApi.list({ limit: 200, sort: "recent" }) });
  const [active, setActive] = useState<string | null>(null);
  const books = q.data?.items ?? [];
  const cols = useMemo(() => collections(books), [books]);
  const newly = books.filter((b) => b.status === "ready").slice(0, 10);
  const shown = active ? cols.find((c) => c.key === active) : null;

  if (q.isPending) return <PageLoader label="Gathering your stories" />;

  return (
    <div className="space-y-14">
      <header>
        <p className="eyebrow text-mint-400/90">Discover</p>
        <h1 className="mt-3 font-display text-4xl font-semibold tracking-tight text-paper-50 sm:text-6xl">Collections worth an evening.</h1>
      </header>

      {books.length === 0 ? (
        <EmptyState icon={<BrandMark className="size-7" />} title="Stories are waiting." action={<ButtonLink to="/create" variant="primary">Create Audiobook</ButtonLink>}>
          Collections appear here as your library grows: unfinished stories, short listens, full-cast novels.
        </EmptyState>
      ) : (
        <>
          <motion.div variants={stagger(0.07)} initial="hidden" animate="show" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {cols.map((c) => (
              <motion.button
                key={c.key}
                type="button"
                variants={reveal}
                onClick={() => setActive(active === c.key ? null : c.key)}
                aria-pressed={active === c.key}
                className={cn(
                  "group relative flex min-h-56 flex-col overflow-hidden rounded-[var(--radius-card)] border p-5 text-left transition-all duration-300 hover:-translate-y-1",
                  active === c.key ? "border-orchid-400/50 shadow-[var(--shadow-glow)]" : "border-white/[0.08] hover:border-white/[0.16]",
                )}
              >
                <div className={cn("absolute inset-0 bg-gradient-to-br opacity-80 transition-opacity duration-500 group-hover:opacity-100", c.gradient)} />
                <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-[2px]" />
                <div className="relative flex items-center justify-between">
                  <c.icon className="size-5 text-paper-200" aria-hidden />
                  <span className="text-xs text-paper-400 tabular-nums">{c.books.length}</span>
                </div>
                <div className="relative mt-auto">
                  <div className="mb-4 flex -space-x-5">
                    {c.books.slice(0, 4).map((b) => (
                      <BookCover key={b.id} url={b.cover_url} title={b.title} size="sm" className="w-12 transition-transform duration-500 group-hover:-translate-y-1" />
                    ))}
                  </div>
                  <h2 className="font-display text-xl font-semibold text-paper-50">{c.title}</h2>
                  <p className="mt-1 text-sm text-paper-400">{c.blurb}</p>
                </div>
              </motion.button>
            ))}
          </motion.div>

          {shown && (
            <section aria-label={shown.title}>
              <h2 className="mb-6 font-display text-2xl font-semibold text-paper-50">{shown.title}</h2>
              {shown.books.length ? (
                <Shelf books={shown.books} />
              ) : (
                <p className="text-sm text-paper-500">Nothing here yet.</p>
              )}
            </section>
          )}

          <motion.section variants={reveal} initial="hidden" whileInView="show" viewport={{ once: true, margin: "-80px" }} aria-labelledby="newly">
            <h2 id="newly" className="mb-6 font-display text-2xl font-semibold text-paper-50">
              Newly narrated
            </h2>
            {newly.length ? <Shelf books={newly} /> : <p className="text-sm text-paper-500">Your finished audiobooks will appear here.</p>}
          </motion.section>
        </>
      )}
    </div>
  );
}

function Shelf({ books }: { books: Book[] }) {
  return (
    <div className="grid grid-cols-2 gap-x-5 gap-y-9 sm:grid-cols-3 lg:grid-cols-5">
      {books.map((b) => (
        <ShelfCard key={b.id} book={b} />
      ))}
    </div>
  );
}
