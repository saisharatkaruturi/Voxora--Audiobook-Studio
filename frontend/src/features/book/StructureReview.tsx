import { useEffect, useMemo, useRef } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { AlertTriangle, ArrowRight, BookOpenText, Check, Circle, Loader2, Users } from "lucide-react";
import { BookStage } from "@/components/brand/BookStage";
import { Badge, Notice, Skeleton } from "@/components/ui/Feedback";
import { ButtonLink } from "@/components/ui/Button";
import { Segmented } from "@/components/ui/Form";
import { toast } from "@/components/ui/Toast";
import { brand } from "@/config/brand";
import { reveal, stagger } from "@/config/motion";
import { aiApi, booksApi, chaptersApi, jobsApi } from "@/services/api";
import { errorMessage } from "@/services/http";
import { qk } from "@/services/queryClient";
import type { Book, Chapter, ContentMode } from "@/types/api";
import { cn, formatDuration, kindLabel, pluralize } from "@/utils/format";

const GROUPS: { key: Chapter["group"]; title: string; blurb: string }[] = [
  { key: "front", title: "Front matter", blurb: "Title pages, dedication, forewords, contents" },
  { key: "narrative", title: "Story", blurb: "What your listeners came for" },
  { key: "back", title: "Back matter", blurb: "Acknowledgements, notes, about the author, ads" },
];

const WORDS_PER_MINUTE = 155; // typical audiobook narration pace

function doubt(c: Chapter): string | null {
  if (c.detection?.skipped === "toc_leftover") return "Looks like a leftover from the table of contents";
  if (c.detection?.skipped === "too_short") return "Too short to be a real section";
  if (typeof c.detection?.confidence === "number" && c.detection.confidence < 0.5) return `${brand.name} isn't completely sure about this section`;
  return null;
}

/** "Understanding your book": what was found, and which parts will be narrated. */
export function StructureReview({ book }: { book: Book }) {
  const qc = useQueryClient();
  const chapters = useQuery({ queryKey: qk.chapters(book.id), queryFn: () => chaptersApi.list(book.id) });
  const cast = useQuery({ queryKey: qk.cast(book.id), queryFn: () => aiApi.cast(book.id) });
  const castJob = useQuery({
    queryKey: ["cast-job", book.id],
    queryFn: () => jobsApi.list({ book_id: book.id, active: true }),
    refetchInterval: (q) => (q.state.data?.items.some((j) => j.type === "cast_analysis") ? 3000 : false),
  });
  const characterSearch = castJob.data?.items.some((j) => j.type === "cast_analysis");
  const items = useMemo(() => chapters.data?.items ?? [], [chapters.data]);
  const mode: ContentMode = book.narration.content_mode ?? "narrative";

  const setList = (list: Chapter[]) => qc.setQueryData(qk.chapters(book.id), { items: list });
  const changeMode = useMutation({
    mutationFn: (m: ContentMode) => booksApi.contentMode(book.id, m),
    onSuccess: (r, m) => {
      setList(r.items);
      qc.setQueryData<Book>(qk.book(book.id), (b) => (b ? { ...b, narration: { ...b.narration, content_mode: m } } : b));
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const toggle = useMutation({
    mutationFn: (c: Chapter) => chaptersApi.update(c.id, { include_in_audio: !c.include_in_audio }),
    onMutate: (c) => {
      setList(items.map((x) => (x.id === c.id ? { ...x, include_in_audio: !x.include_in_audio } : x)));
      qc.setQueryData<Book>(qk.book(book.id), (b) => (b ? { ...b, narration: { ...b.narration, content_mode: "custom" } } : b));
    },
    onError: (e) => {
      toast.error(errorMessage(e));
      void qc.invalidateQueries({ queryKey: qk.chapters(book.id) });
    },
  });

  // When the background character pass finishes, refresh the cast.
  const wasSearching = useRef(false);
  useEffect(() => {
    if (wasSearching.current && characterSearch === false) void qc.invalidateQueries({ queryKey: qk.cast(book.id) });
    wasSearching.current = !!characterSearch;
  }, [characterSearch, qc, book.id]);

  const narrated = items.filter((c) => c.include_in_audio);
  const words = narrated.reduce((n, c) => n + c.word_count, 0);
  const chapterCount = items.filter((c) => c.kind === "chapter").length;
  const optional = items.filter((c) => c.group !== "narrative").length;
  const hasToc = items.some((c) => c.kind === "toc");
  const doubts = items.filter((c) => doubt(c) && c.detection?.skipped === undefined).length;
  const characters = (cast.data?.items ?? []).filter((m) => m.role === "character");

  const findings: { ok: boolean; label: string; pending?: boolean }[] = [
    { ok: true, label: `Book identified: ${book.title}` },
    { ok: !!book.author, label: book.author ? `Author identified: ${book.author}` : "Author not found in the file; add it in Book Studio" },
    { ok: hasToc, label: hasToc ? "Table of contents detected" : "No table of contents found; chapters came from headings" },
    { ok: chapterCount > 0, label: `${pluralize(chapterCount, "chapter")} found` },
    { ok: true, label: `${pluralize(optional, "front/back matter section")} found` },
    { ok: true, label: book.ocr_used ? `Scanned pages read (${Math.round((book.ocr_confidence ?? 0) * 100)}% confidence)` : "Narrative text cleaned" },
    characterSearch
      ? { ok: false, pending: true, label: "Finding characters…" }
      : { ok: characters.length > 0, label: characters.length ? `${pluralize(characters.length, "character")} detected` : "No recurring speaking characters found" },
  ];

  return (
    <div className="space-y-10">
      <section className="grid items-center gap-8 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="relative h-72 sm:h-80">
          <BookStage mode="open" className="absolute inset-0" fallbackSize={220} zoom={1.05} interactive={false} />
        </div>
        <div>
          <p className="eyebrow text-mint-400/90">Ready for narration</p>
          <h1 className="mt-3 font-display text-4xl font-semibold tracking-tight text-paper-50 sm:text-5xl">Understanding your book.</h1>
          <motion.ul variants={stagger(0.08)} initial="hidden" animate="show" className="mt-6 space-y-2.5" aria-label="What VOXORA found">
            {findings.map((f) => (
              <motion.li key={f.label} variants={reveal} className="flex items-center gap-3 text-sm">
                <span className={cn("flex size-6 shrink-0 items-center justify-center rounded-full", f.ok ? "bg-mint-400/15 text-mint-400" : f.pending ? "bg-orchid-500/15 text-orchid-300" : "bg-white/[0.06] text-paper-500")}>
                  {f.pending ? <Loader2 className="size-3.5 animate-spin" /> : f.ok ? <Check className="size-3.5" strokeWidth={3} /> : <Circle className="size-3" />}
                </span>
                <span className={f.ok ? "text-paper-100" : "text-paper-400"}>{f.label}</span>
              </motion.li>
            ))}
          </motion.ul>
        </div>
      </section>

      <section className="surface p-5 sm:p-7" aria-labelledby="structure">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 id="structure" className="font-display text-2xl font-semibold text-paper-50">
              Book structure
            </h2>
            <p className="mt-1 text-sm text-paper-400">
              {pluralize(narrated.length, "section")} narrated · {words.toLocaleString()} words · about {formatDuration((words / WORDS_PER_MINUTE) * 60)} of listening
            </p>
          </div>
          <Segmented<ContentMode>
            label="What to narrate"
            value={mode}
            onChange={(m) => m !== "custom" && changeMode.mutate(m)}
            options={[
              { value: "narrative", label: "Narrative only" },
              { value: "full", label: "Full book" },
              { value: "custom", label: "Custom" },
            ]}
          />
        </div>
        <p className="mt-2 text-xs text-paper-500">
          {mode === "narrative"
            ? "Prologue, chapters, epilogue and afterword. Copyright pages, acknowledgements, author bio and ads are left out."
            : mode === "full"
              ? "Every meaningful section, including forewords, acknowledgements and notes. Contents pages and ads are still left out."
              : "Your own selection. Toggle any section below."}
        </p>
        {doubts > 0 && (
          <Notice kind="warning" className="mt-4" title={`${brand.name} isn't completely sure about ${pluralize(doubts, "section")}`}>
            They're marked below. Check them in Book Studio before creating the audiobook.
          </Notice>
        )}

        {chapters.isPending ? (
          <Skeleton className="mt-6 h-64" />
        ) : (
          <div className="mt-6 grid gap-4 lg:grid-cols-3">
            {GROUPS.map((g) => {
              const list = items.filter((c) => c.group === g.key);
              return (
                <div key={g.key} className={cn("rounded-2xl border p-3", g.key === "narrative" ? "border-orchid-400/25 bg-orchid-500/[0.04] lg:order-none" : "border-white/[0.06] bg-white/[0.02]")}>
                  <div className="flex items-baseline justify-between px-2 pt-1 pb-2">
                    <h3 className="text-sm font-semibold text-paper-100">{g.title}</h3>
                    <span className="text-[11px] text-paper-500">
                      {list.filter((c) => c.include_in_audio).length}/{list.length} narrated
                    </span>
                  </div>
                  <p className="px-2 pb-2 text-[11px] text-paper-500">{g.blurb}</p>
                  {list.length === 0 ? (
                    <p className="px-2 py-4 text-xs text-paper-500">None found.</p>
                  ) : (
                    <ul className="max-h-[420px] space-y-0.5 overflow-y-auto pr-1">
                      {list.map((c) => {
                        const why = doubt(c);
                        return (
                          <li key={c.id}>
                            <label className="flex cursor-pointer items-start gap-3 rounded-xl px-2 py-2 hover:bg-white/[0.04]">
                              <input type="checkbox" checked={c.include_in_audio} onChange={() => toggle.mutate(c)} className="mt-0.5 size-4 shrink-0 accent-orchid-500" aria-label={`Narrate ${c.title}`} />
                              <span className="min-w-0 flex-1">
                                <span className={cn("block truncate text-[13px]", c.include_in_audio ? "text-paper-100" : "text-paper-400")}>{c.title}</span>
                                <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-paper-500">
                                  {kindLabel(c.kind)} · {c.word_count.toLocaleString()} words
                                  {why && (
                                    <span className="inline-flex items-center gap-1 text-amber-300" title={why}>
                                      <AlertTriangle className="size-3" /> {why}
                                    </span>
                                  )}
                                </span>
                              </span>
                            </label>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>

      {characters.length > 0 && (
        <section aria-labelledby="chars" className="surface p-5 sm:p-7">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 id="chars" className="flex items-center gap-2 font-display text-xl font-semibold text-paper-50">
              <Users className="size-5 text-orchid-300" /> Characters
            </h2>
            <Link to={`/books/${book.id}/cast`} className="text-sm text-orchid-300 hover:underline">
              Give them voices in AI Cast
            </Link>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {characters.slice(0, 18).map((m) => (
              <Badge key={m.id} className="px-3 py-1 text-xs">
                {m.name} <span className="text-paper-500">· {m.line_count} lines</span>
              </Badge>
            ))}
          </div>
        </section>
      )}

      <div className="flex flex-wrap items-center justify-end gap-2">
        <ButtonLink to={`/books/${book.id}/edit`} icon={<BookOpenText className="size-4" />}>
          Open Book Studio
        </ButtonLink>
        <ButtonLink to={`/books/${book.id}/voice`} variant="primary" size="lg">
          Continue to Voice Studio <ArrowRight className="size-4" />
        </ButtonLink>
      </div>
    </div>
  );
}
