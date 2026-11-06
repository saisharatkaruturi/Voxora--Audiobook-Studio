import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowRight, Check, CircleDashed, Clock, Headphones, Loader2, Minus, Pause, Play, RefreshCw, Square } from "lucide-react";
import { BookCover } from "@/components/book/BookCover";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Notice, ProgressBar } from "@/components/ui/Feedback";
import { toast } from "@/components/ui/Toast";
import { useBookContext } from "@/features/book/BookLayout";
import { booksApi, chaptersApi, jobsApi } from "@/services/api";
import { errorMessage } from "@/services/http";
import { qk } from "@/services/queryClient";
import type { BookSnapshot, Job, JobStage } from "@/types/api";
import { cn, formatDuration } from "@/utils/format";
import { BookStage } from "@/components/brand/BookStage";
import { StructureReview } from "@/features/book/StructureReview";
import { Link } from "react-router-dom";
import { brand } from "@/config/brand";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";

const PIPELINE = new Set(["analyze", "generate_book", "generate_chapter"]);

export default function ProcessingPage() {
  const { book, live } = useBookContext();
  const qc = useQueryClient();
  useDocumentTitle("Book Studio");
  const chapters = useQuery({ queryKey: qk.chapters(book.id), queryFn: () => chaptersApi.list(book.id) });

  const job: Job | null = live?.job && PIPELINE.has(live.job.type) ? live.job : book.active_job && PIPELINE.has(book.active_job.type) ? book.active_job : null;
  const status = live?.book.status ?? book.status;
  const isGeneration = job?.type === "generate_book" || job?.type === "generate_chapter";
  const running = job && (job.status === "queued" || job.status === "running");

  // Merge live per-chapter status over the fetched list.
  const chapterRows = useMemo(() => {
    const liveMap = new Map((live?.chapters ?? []).map((c) => [c.id, c]));
    return (chapters.data?.items ?? []).map((c) => ({ ...c, ...(liveMap.get(c.id) ?? {}) }));
  }, [chapters.data, live]);

  const act = useMutation({
    mutationFn: async (action: "pause" | "resume" | "cancel" | "retry" | "reanalyze" | "generate") => {
      if (action === "reanalyze") return booksApi.analyze(book.id);
      if (action === "generate") return booksApi.generate(book.id);
      if (!job) throw new Error("No job to control.");
      return jobsApi[action](job.id);
    },
    onSuccess: (_d, action) => {
      const msg = { pause: "Pausing after the current chunk.", resume: "Resuming. Finished chapters are kept.", cancel: "Cancelled.", retry: "Retrying.", reanalyze: "Analysis restarted.", generate: "Generation started." }[action];
      toast.info(msg);
      void qc.invalidateQueries({ queryKey: qk.book(book.id) });
      void qc.invalidateQueries({ queryKey: qk.chapters(book.id) });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const retryChapter = useMutation({
    mutationFn: (id: string) => chaptersApi.generate(id),
    onSuccess: () => {
      toast.info("Retrying that chapter. Other chapters are untouched.");
      void qc.invalidateQueries({ queryKey: qk.book(book.id) });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const title = headline(status, job);
  const eta = typeof job?.result?.eta_seconds === "number" && running ? (job.result.eta_seconds as number) : null;
  const narrated = chapterRows.filter((c) => c.include_in_audio);
  const justFinished = isGeneration && job?.status === "completed" && status === "ready";

  if (status === "review" && !running && job?.status !== "failed" && !chapterRows.some((c) => c.audio_status === "done")) {
    return <StructureReview book={book} />;
  }
  const firstReady = chapterRows.find((c) => c.include_in_audio && c.audio_status === "done");
  const telemetry = (job?.result?.telemetry ?? null) as Record<string, number | string | null> | null;

  return (
    <div className="grid gap-8 lg:grid-cols-[280px_1fr]">
      <aside className="space-y-4">
        <BookCover url={book.cover_url} title={book.title} author={book.author} className="mx-auto w-48 lg:w-full" size="lg" />
        <div className="text-center lg:text-left">
          <h2 className="font-display text-xl text-paper-50">{book.title}</h2>
          <p className="text-sm text-paper-400">{book.author || "Unknown author"}</p>
        </div>
        <dl className="grid grid-cols-2 gap-2 text-sm">
          <Stat label="Format" value={book.source_format.toUpperCase()} />
          <Stat label="Pages" value={book.page_count ?? "—"} />
          <Stat label="Words" value={book.word_count ? book.word_count.toLocaleString() : "—"} />
          <Stat label="Chapters" value={book.chapter_count ?? "—"} />
        </dl>
      </aside>

      <section className="space-y-6">
        {justFinished && (
          <div className="surface relative flex flex-col items-center overflow-hidden px-6 pt-4 pb-10 text-center">
            <BookStage mode="open" className="h-60 w-full" fallbackSize={200} zoom={1.1} interactive={false} />
            <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight text-paper-50">Your story is alive.</h1>
            <p className="mt-2 text-paper-400">Your {brand.name} audiobook is ready.</p>
            <div className="mt-7 flex flex-wrap justify-center gap-2">
              <ButtonLink to={`/books/${book.id}/listen`} variant="primary" size="lg" icon={<Headphones className="size-4" />}>
                Start Listening
              </ButtonLink>
              <ButtonLink to={`/books/${book.id}`} size="lg">
                View Book
              </ButtonLink>
            </div>
          </div>
        )}
        {!justFinished && (
        <div className="surface relative overflow-hidden p-6 sm:p-8">
          {running && (
            <div className="-mx-6 -mt-6 mb-2 h-56 sm:-mx-8 sm:-mt-8" aria-hidden>
              <BookStage mode="flowing" className="h-full w-full" fallbackSize={170} zoom={1.15} interactive={false} />
            </div>
          )}
          <p className="eyebrow">{isGeneration ? "Creating your audiobook" : "Reading your book"}</p>
          <h1 className="mt-2 font-display text-3xl font-semibold tracking-tight text-paper-50">{title}</h1>
          {job?.message && <p className="mt-2 text-sm text-paper-400">{job.message}</p>}

          {job && job.progress > 0 && job.status !== "completed" && (
            <div className="mt-6 space-y-2">
              <ProgressBar value={job.progress} label="Overall progress" />
              <div className="flex justify-between text-xs text-paper-500 tabular-nums">
                <span>{Math.round(job.progress)}%{isGeneration && job.total_chapters ? ` · chapter ${job.current_chapter ?? 0} of ${job.total_chapters}` : ""}</span>
                {eta !== null && <span>about {formatDuration(eta)} left</span>}
              </div>
            </div>
          )}

          {job && <StageList stages={job.stages} jobStatus={job.status} />}

          <div className="mt-8 flex flex-wrap gap-2">
            {running && (
              <>
                <Button icon={<Pause className="size-4" />} onClick={() => act.mutate("pause")} loading={act.isPending && act.variables === "pause"}>
                  Pause
                </Button>
                <Button variant="ghost" icon={<Square className="size-4" />} onClick={() => act.mutate("cancel")}>
                  Cancel
                </Button>
              </>
            )}
            {job?.status === "paused" && (
              <Button variant="primary" icon={<Play className="size-4" />} onClick={() => act.mutate("resume")} loading={act.isPending}>
                Resume
              </Button>
            )}
            {job?.status === "failed" && (
              <Button variant="primary" icon={<RefreshCw className="size-4" />} onClick={() => act.mutate(job.type === "analyze" ? "reanalyze" : "retry")} loading={act.isPending}>
                {job.type === "analyze" ? "Try analysis again" : "Resume generation"}
              </Button>
            )}
            {status === "review" && !running && (
              <>
                <ButtonLink to={`/books/${book.id}/edit`} variant="primary" icon={<ArrowRight className="size-4" />}>
                  Review chapters
                </ButtonLink>
                <ButtonLink to={`/books/${book.id}/voice`}>Choose a narrator</ButtonLink>
              </>
            )}
            {status === "ready" && !running && !justFinished && (
              <ButtonLink to={`/books/${book.id}/listen`} variant="primary" icon={<Headphones className="size-4" />}>
                Open audiobook
              </ButtonLink>
            )}
            {status === "uploaded" && !job && (
              <Button variant="primary" onClick={() => act.mutate("reanalyze")} loading={act.isPending}>
                Read this book
              </Button>
            )}
          </div>
        </div>
        )}

        {(job?.status === "failed" || status === "failed") && (job?.error || book.error) && (
          <Notice kind="error" title={job?.type === "analyze" || book.error?.stage === "analysis" ? "Analysis failed" : "Generation stopped"}>
            {(job?.error ?? book.error)?.message}
            {(job?.error ?? book.error)?.retryable ? " This looks temporary, so trying again should work." : ""}
          </Notice>
        )}
        {telemetry && <Telemetry t={telemetry} generation={isGeneration} />}

        {book.warnings.length > 0 && status !== "analyzing" && (
          <Notice kind="warning" title="Things to check">
            <ul className="list-disc space-y-1 pl-4">
              {book.warnings.slice(0, 6).map((w, i) => (
                <li key={i}>{typeof w === "string" ? w : w.message}</li>
              ))}
            </ul>
          </Notice>
        )}
        {book.ocr_used && book.ocr_confidence !== null && (
          <Notice kind={book.ocr_confidence < 0.7 ? "warning" : "info"} title={`OCR confidence ${Math.round(book.ocr_confidence * 100)}%`}>
            {book.ocr_confidence < 0.7
              ? "The scan was hard to read. Review the text in the editor before generating audio."
              : `Scanned pages were read with ${book.ocr_engine ?? "OCR"}.`}
          </Notice>
        )}

        {running && isGeneration && firstReady && (
          <Notice
            kind="success"
            title={`${firstReady.title} is ready`}
            action={
              <ButtonLink to={`/books/${book.id}/listen?chapter=${firstReady.id}`} size="sm" variant="primary" icon={<Headphones className="size-4" />}>
                Start listening
              </ButtonLink>
            }
          >
            Listen now while the rest of the book is created. Finished chapters appear in the player as they're ready.
          </Notice>
        )}

        {narrated.length > 0 && (isGeneration || status === "ready" || status === "generating" || chapterRows.some((c) => c.audio_status !== "pending")) && (
          <div className="surface p-2 sm:p-3">
            <p className="eyebrow px-3 pt-2 pb-3">Chapters</p>
            <ol className="divide-y divide-white/[0.04]">
              {narrated.map((c) => (
                <li key={c.id} className="flex items-center gap-3 px-3 py-3">
                  <ChapterStatusIcon status={c.audio_status} />
                  <div className="min-w-0 flex-1">
                    <p className={cn("truncate text-sm", c.audio_status === "done" ? "text-paper-100" : "text-paper-300")}>{c.title}</p>
                    {c.audio_status === "generating" && <ProgressBar value={c.audio_progress} className="mt-2 h-1 max-w-xs" label={`${c.title} progress`} />}
                    {c.audio_status === "failed" && c.audio_error && <p className="mt-1 text-xs text-rose-400">{c.audio_error.message}</p>}
                  </div>
                  <span className="text-xs text-paper-500 tabular-nums">
                    {c.audio_status === "done"
                      ? formatDuration(c.duration)
                      : c.audio_status === "generating"
                        ? `${Math.round(c.audio_progress)}%`
                        : c.audio_status === "queued"
                          ? "Waiting"
                          : c.audio_status === "failed"
                            ? ""
                            : "Not generated"}
                  </span>
                  {c.audio_status === "done" && (
                    <Link
                      to={`/books/${book.id}/listen?chapter=${c.id}`}
                      className="neo flex size-8 items-center justify-center rounded-full text-paper-100 hover:text-mint-400"
                      aria-label={`Listen to ${c.title}`}
                    >
                      <Play className="size-3.5 translate-x-px fill-current" />
                    </Link>
                  )}
                  {c.audio_status === "failed" && !running && (
                    <Button size="sm" variant="secondary" onClick={() => retryChapter.mutate(c.id)} loading={retryChapter.isPending && retryChapter.variables === c.id}>
                      Retry Chapter
                    </Button>
                  )}
                </li>
              ))}
            </ol>
          </div>
        )}
      </section>
    </div>
  );
}

function headline(status: BookSnapshot["book"]["status"], job: Job | null): string {
  if (job?.status === "paused") return "Paused";
  if (job?.status === "failed") return job.type === "analyze" ? `${brand.name} couldn't finish reading this book` : "Generation paused on an error";
  if (status === "analyzing" || (job?.type === "analyze" && job.status !== "completed")) return `${brand.name} is reading the pages…`;
  if (status === "generating") return `${brand.name} is bringing your story to life.`;
  if (status === "review") return "Your book is ready to review";
  if (status === "ready") return "Your story is ready.";
  if (status === "failed") return "Something needs your attention";
  return "Waiting to start";
}

function StageList({ stages, jobStatus }: { stages: JobStage[]; jobStatus: string }) {
  if (!stages.length) return null;
  return (
    <ol className="mt-8 space-y-3.5" aria-label="Processing steps">
      {stages.map((s) => {
        const state = jobStatus === "failed" && s.status === "active" ? "failed" : jobStatus === "completed" && s.status === "active" ? "done" : s.status;
        return (
          <li key={s.key} className="flex items-center gap-3">
            <span
              className={cn(
                "flex size-6 shrink-0 items-center justify-center rounded-full",
                state === "done" && "bg-sage-400/15 text-sage-400",
                state === "active" && "bg-orchid-500/15 text-orchid-400",
                state === "failed" && "bg-rose-400/15 text-rose-400",
                (state === "pending" || state === "skipped") && "bg-white/[0.05] text-paper-500",
              )}
              aria-hidden
            >
              {state === "done" ? (
                <Check className="size-3.5" strokeWidth={3} />
              ) : state === "active" ? (
                jobStatus === "paused" ? <Pause className="size-3" /> : <Loader2 className="size-3.5 animate-spin" />
              ) : state === "failed" ? (
                <AlertCircle className="size-3.5" />
              ) : state === "skipped" ? (
                <Minus className="size-3" />
              ) : (
                <CircleDashed className="size-3.5" />
              )}
            </span>
            <span className={cn("text-sm", state === "active" ? "font-medium text-paper-50" : state === "done" ? "text-paper-200" : "text-paper-500", state === "skipped" && "line-through")}>
              {s.label}
            </span>
            <span className="sr-only">({state})</span>
          </li>
        );
      })}
    </ol>
  );
}

function ChapterStatusIcon({ status }: { status: string }) {
  const map: Record<string, { icon: typeof Check; cls: string; label: string }> = {
    done: { icon: Check, cls: "bg-sage-400/15 text-sage-400", label: "Done" },
    generating: { icon: Loader2, cls: "bg-orchid-500/15 text-orchid-400", label: "Generating" },
    queued: { icon: Clock, cls: "bg-white/[0.05] text-paper-400", label: "Waiting" },
    failed: { icon: AlertCircle, cls: "bg-rose-400/15 text-rose-400", label: "Failed" },
    pending: { icon: CircleDashed, cls: "bg-white/[0.04] text-paper-500", label: "Not generated" },
    skipped: { icon: Minus, cls: "bg-white/[0.04] text-paper-500", label: "Skipped" },
  };
  const m = map[status] ?? map.pending;
  const Icon = m.icon;
  return (
    <span className={cn("flex size-7 shrink-0 items-center justify-center rounded-full", m.cls)} title={m.label}>
      <Icon className={cn("size-3.5", status === "generating" && "animate-spin")} strokeWidth={status === "done" ? 3 : 2} aria-label={m.label} />
    </span>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-white/[0.05] bg-white/[0.02] px-3 py-2">
      <dt className="text-[11px] text-paper-500">{label}</dt>
      <dd className="text-sm text-paper-100 tabular-nums">{value}</dd>
    </div>
  );
}

function Telemetry({ t, generation }: { t: Record<string, number | string | null>; generation: boolean }) {
  const n = (k: string) => (typeof t[k] === "number" ? (t[k] as number) : null);
  const rows: [string, string][] = generation
    ? [
        ["Audio created", formatDuration(n("audio_seconds"))],
        ["Synthesis time", formatDuration(n("tts_seconds"))],
        ["Encoding time", formatDuration(n("encode_seconds"))],
        ["Speed", n("realtime_factor") ? `${n("realtime_factor")}× realtime` : "measuring…"],
        ["Throughput", n("chars_per_second") ? `${Math.round(n("chars_per_second")!)} characters/s` : "measuring…"],
        ["Parallel voices", n("workers") ? String(n("workers")) : "—"],
        ["Reused from cache", n("chunks") ? `${n("cached_chunks") ?? 0} of ${n("chunks")} chunks` : "—"],
      ]
    : [
        ["Text extraction", formatDuration(n("extract_seconds"))],
        ...(n("ocr_seconds") !== null ? ([["Scanned pages (OCR)", formatDuration(n("ocr_seconds"))]] as [string, string][]) : []),
        ["Cleaning", formatDuration(n("clean_seconds"))],
        ["Finding chapters", formatDuration(n("structure_seconds"))],
        ["Total", formatDuration(n("total_seconds"))],
        ["Pages per minute", n("pages_per_minute") ? String(n("pages_per_minute")) : "—"],
      ];
  return (
    <details className="surface group p-5">
      <summary className="cursor-pointer list-none text-sm font-medium text-paper-200">Performance details</summary>
      <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt className="text-xs text-paper-500">{k}</dt>
            <dd className="text-paper-100 tabular-nums">{v}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
