import { useRef, useState, type DragEvent } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { BookOpenText, Check, ChevronDown, FileText, ImageIcon, Library, Mic2, RotateCcw, ShieldCheck, UploadCloud, X } from "lucide-react";
import { HeroWaveform } from "@/components/audio/AudioWaveform";
import { BookStage } from "@/components/brand/BookStage";
import type { SceneMode } from "@/components/3d/HeroScene";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Field, Select } from "@/components/ui/Form";
import { Notice } from "@/components/ui/Feedback";
import { brand } from "@/config/brand";
import { ease } from "@/config/motion";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { useJob } from "@/hooks/useJob";
import { booksApi, systemApi } from "@/services/api";
import { errorMessage } from "@/services/http";
import { qk } from "@/services/queryClient";
import { ACCEPTED_EXTENSIONS, uploadBook, validateFile } from "@/services/upload";
import type { Book, Job } from "@/types/api";
import { cn, formatBytes, pluralize } from "@/utils/format";

type Phase = "idle" | "selected" | "uploading" | "reading" | "done" | "error";

/** The signature interaction: the 3D book reacts to every phase. */
const SCENE: Record<Phase, SceneMode> = { idle: "closed", selected: "open", uploading: "absorb", reading: "absorb", done: "sealed", error: "open" };

function typeLabel(file: File): string {
  return file.name.split(".").pop()?.toUpperCase() ?? "FILE";
}

export default function UploadPage() {
  useDocumentTitle("Create Audiobook");
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const abort = useRef<AbortController | null>(null);
  const bookRef = useRef<Book | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [language, setLanguage] = useState("auto");
  const [ocrMode, setOcrMode] = useState("auto");
  const [progress, setProgress] = useState(0);
  const [jobId, setJobId] = useState<string | null>(null);
  const [book, setBook] = useState<Book | null>(null);
  const status = useQuery({ queryKey: qk.status, queryFn: systemApi.status, staleTime: 60_000 });
  const maxMb = status.data?.limits.max_file_size_mb ?? 300;

  const job = useJob(jobId, async (j: Job) => {
    const current = bookRef.current;
    if (j.status === "completed" && current) {
      const fresh = await booksApi.get(current.id);
      setBook(fresh);
      qc.setQueryData(qk.book(fresh.id), fresh);
      void qc.invalidateQueries({ queryKey: ["books"] });
      setPhase("done");
    } else if (j.status !== "completed") {
      setError(j.error?.message ?? `${brand.name} couldn't read this book.`);
      setPhase("error");
    }
  });

  const choose = (f: File | undefined | null) => {
    if (!f || phase === "uploading" || phase === "reading") return;
    const problem = validateFile(f, maxMb);
    setError(problem);
    if (!problem) {
      setFile(f);
      setPhase("selected");
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files.length > 1) setError("Bring one book at a time.");
    choose(e.dataTransfer.files[0]);
  };

  const start = async () => {
    if (!file) return;
    setError(null);
    setProgress(0);
    setPhase("uploading");
    abort.current = new AbortController();
    try {
      const res = await uploadBook(file, { language, ocrMode, autoAnalyze: true }, setProgress, abort.current.signal);
      bookRef.current = res.book;
      setBook(res.book);
      setJobId(res.job?.id ?? null);
      setPhase("reading");
    } catch (err) {
      if ((err as Error).name === "AbortError") setPhase("selected");
      else {
        setError(errorMessage(err));
        setPhase("error");
      }
    }
  };

  const retry = async () => {
    if (!book) return void start();
    try {
      const j = await booksApi.analyze(book.id);
      setError(null);
      setJobId(j.id);
      setPhase("reading");
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const reset = () => {
    bookRef.current = null;
    setFile(null);
    setBook(null);
    setJobId(null);
    setError(null);
    setPhase("idle");
  };

  const busy = phase === "uploading" || phase === "reading";
  const stages = job?.stages ?? [];
  const current = phase === "uploading" ? (progress < 1 ? "Bringing your book in…" : "Opening the file…") : (job?.message ?? "Reading your book…");

  return (
    <div className="space-y-8">
      <header className="max-w-3xl">
        <p className="eyebrow text-mint-400/90">Create</p>
        <h1 className="mt-3 font-display text-4xl font-semibold tracking-tight text-paper-50 sm:text-6xl">Drop a book into {brand.name}.</h1>
        <p className="mt-3 text-paper-400">PDF · EPUB · DOCX · TXT · scanned pages</p>
      </header>

      <section className="relative grid items-stretch gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
        <div
          onDragOver={(e) => {
            e.preventDefault();
            if (!busy) setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cn("surface relative flex min-h-[440px] flex-col overflow-visible p-6 transition-[border-color,box-shadow] duration-300 sm:p-8", dragging && "border-orchid-400/60 shadow-[var(--shadow-glow)]")}
        >
          <AnimatePresence mode="wait">
            {!file ? (
              <motion.div key="drop" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }} transition={{ duration: 0.4, ease: ease.out }} className="flex flex-1 flex-col items-center justify-center text-center">
                <div className={cn("neo flex size-20 items-center justify-center rounded-3xl transition-colors", dragging ? "text-mint-400" : "text-paper-200")}>
                  <UploadCloud className="size-8" aria-hidden />
                </div>
                <p className="mt-6 font-display text-2xl text-paper-50">{dragging ? "Let go to bring it in" : "Drag a file here"}</p>
                <p className="mt-2 text-sm text-paper-400">
                  or{" "}
                  <button type="button" onClick={() => input.current?.click()} className="font-medium text-orchid-300 underline-offset-4 hover:underline">
                    browse files
                  </button>
                </p>
                <p className="mt-8 text-xs text-paper-500">Up to {maxMb} MB. Scanned pages are recognized automatically.</p>
                {error && (
                  <Notice kind="error" className="mt-6 text-left">
                    {error}
                  </Notice>
                )}
              </motion.div>
            ) : (
              <motion.div key="doc" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease: ease.out }} className="flex flex-1 flex-col">
                <DocumentSheets file={file} lifting={busy} gone={phase === "done"} />
                <div className="mt-6 flex items-start gap-4">
                  <div className="neo flex size-11 shrink-0 items-center justify-center rounded-xl text-orchid-300">
                    {file.type.startsWith("image/") ? <ImageIcon className="size-5" /> : <FileText className="size-5" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium text-paper-50" title={file.name}>
                      {file.name}
                    </p>
                    <p className="text-sm text-paper-400">
                      {formatBytes(file.size)} · {typeLabel(file)}
                    </p>
                  </div>
                  {phase === "selected" && (
                    <button type="button" onClick={reset} className="rounded-lg p-1.5 text-paper-500 hover:bg-white/[0.06] hover:text-paper-100" aria-label="Remove file">
                      <X className="size-4" />
                    </button>
                  )}
                </div>

                {phase === "selected" && (
                  <>
                    <details className="group mt-5 rounded-2xl border border-white/[0.06] px-4 py-3">
                      <summary className="flex cursor-pointer list-none items-center justify-between text-sm text-paper-300">
                        Reading options <ChevronDown className="size-4 transition-transform group-open:rotate-180" />
                      </summary>
                      <div className="mt-4 grid gap-4 sm:grid-cols-2">
                        <Field label="Language" htmlFor="lang" hint="Detected per paragraph for mixed-language books.">
                          <Select id="lang" value={language} onChange={(e) => setLanguage(e.target.value)}>
                            <option value="auto">Detect automatically</option>
                            {status.data?.languages.map((l) => (
                              <option key={l.code} value={l.code}>
                                {l.name}
                              </option>
                            ))}
                          </Select>
                        </Field>
                        <Field label="Scanned pages (OCR)" htmlFor="ocr">
                          <Select id="ocr" value={ocrMode} onChange={(e) => setOcrMode(e.target.value)}>
                            <option value="auto">Automatic</option>
                            <option value="force">Read every page as a scan</option>
                            <option value="off">Never</option>
                          </Select>
                        </Field>
                      </div>
                    </details>
                    <div className="mt-auto flex flex-wrap items-center justify-between gap-3 pt-6">
                      <p className="flex items-center gap-2 text-xs text-paper-500">
                        <ShieldCheck className="size-4 text-mint-400" aria-hidden />
                        {status.data?.storage.local ? "Stays on this server." : "Stored in your configured storage."}
                      </p>
                      <Button variant="primary" size="lg" onClick={() => void start()}>
                        Add to {brand.name}
                      </Button>
                    </div>
                  </>
                )}

                {busy && (
                  <div className="mt-6 space-y-4" aria-live="polite">
                    <HeroWaveform active className="h-12" label="Reading in progress" />
                    <p className="text-sm text-paper-200">{current}</p>
                    {phase === "uploading" && (
                      <div className="h-1 overflow-hidden rounded-full bg-white/[0.08]">
                        <div className="h-full bg-orchid-500 transition-[width] duration-300" style={{ width: `${Math.round(progress * 100)}%` }} />
                      </div>
                    )}
                    {stages.length > 0 && (
                      <ol className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-3">
                        {stages.map((s) => (
                          <li key={s.key} className={cn("flex items-center gap-1.5", s.status === "done" ? "text-mint-400" : s.status === "active" ? "text-paper-100" : "text-paper-500", s.status === "skipped" && "line-through opacity-60")}>
                            {s.status === "done" ? <Check className="size-3" /> : <span className={cn("size-1.5 rounded-full", s.status === "active" ? "animate-pulse-soft bg-orchid-400" : "bg-paper-500")} />}
                            {s.label}
                          </li>
                        ))}
                      </ol>
                    )}
                    {phase === "uploading" && (
                      <Button variant="ghost" size="sm" onClick={() => abort.current?.abort()}>
                        Cancel
                      </Button>
                    )}
                  </div>
                )}

                {phase === "done" && book && (
                  <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, ease: ease.out, delay: 0.5 }} className="mt-6">
                    <p className="eyebrow text-mint-400">In your library</p>
                    <h2 className="mt-2 font-display text-2xl font-semibold text-paper-50">{book.title}</h2>
                    <p className="text-sm text-paper-400">
                      {book.author ? `by ${book.author} · ` : ""}
                      {pluralize(book.chapter_count ?? 0, "section")} found{book.ocr_used ? " · read from scans" : ""}
                    </p>
                    <p className="mt-3 text-sm text-paper-300">Next, check what will be narrated, then give it a voice. Nothing is narrated until you choose.</p>
                    <div className="mt-5 flex flex-wrap gap-2">
                      <ButtonLink to={`/books/${book.id}/processing`} variant="primary" icon={<BookOpenText className="size-4" />}>
                        Review structure
                      </ButtonLink>
                      <ButtonLink to={`/books/${book.id}/voice`} icon={<Mic2 className="size-4" />}>
                        Choose a voice
                      </ButtonLink>
                      <ButtonLink to="/library" variant="ghost" icon={<Library className="size-4" />}>
                        Library
                      </ButtonLink>
                    </div>
                    {book.warnings.length > 0 && (
                      <Notice kind="warning" className="mt-5">
                        {typeof book.warnings[0] === "string" ? book.warnings[0] : book.warnings[0].message}
                      </Notice>
                    )}
                  </motion.div>
                )}

                {phase === "error" && (
                  <div className="mt-6 space-y-3">
                    <Notice kind="error" title={`${brand.name} couldn't read this book`}>
                      {error}
                    </Notice>
                    <div className="flex gap-2">
                      <Button icon={<RotateCcw className="size-4" />} onClick={() => void retry()}>
                        Try again
                      </Button>
                      <Button variant="ghost" onClick={reset}>
                        Choose another file
                      </Button>
                    </div>
                  </div>
                )}
              </motion.div>
            )}
          </AnimatePresence>
          <input
            ref={input}
            type="file"
            className="sr-only"
            accept={ACCEPTED_EXTENSIONS.join(",")}
            aria-label="Choose a book file"
            onChange={(e) => {
              choose(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
        </div>

        <div className="relative h-[360px] sm:h-[440px] lg:h-auto lg:min-h-[520px]">
          <BookStage mode={SCENE[phase]} className="absolute inset-0" fallbackSize={220} zoom={1.05} />
          <p className="absolute inset-x-0 bottom-2 text-center text-xs text-paper-500">
            {phase === "idle" ? "Only books you own or may use. No DRM removal." : phase === "done" ? "Safe in your library." : ""}
          </p>
        </div>
      </section>
      {phase === "done" && (
        <p className="text-center text-sm text-paper-500">
          <Link to="/create" onClick={reset} className="text-orchid-300 hover:underline">
            Bring another book
          </Link>
        </p>
      )}
    </div>
  );
}

/** The dropped file as a small stack of pages; while it's being read, sheets lift away toward the book. */
function DocumentSheets({ file, lifting, gone }: { file: File; lifting: boolean; gone: boolean }) {
  return (
    <div className="relative mx-auto mt-2 h-44 w-36 [perspective:800px]" aria-hidden>
      {[0, 1, 2, 3, 4].map((i) => (
        <div
          key={i}
          className={cn(
            "absolute inset-0 rounded-md border border-black/10 bg-gradient-to-br from-[#f7f3ea] to-[#d6cfc0] p-3 shadow-[0_10px_30px_-10px_rgb(0_0_0/0.7)] transition-opacity duration-700",
            lifting && "animate-[vx-sheet-fly_2.4s_var(--ease-out-soft)_infinite]",
            gone && "opacity-0",
          )}
          style={{ transform: `translate(${i * 3}px, ${-i * 3}px) rotate(${(i - 2) * 1.2}deg)`, animationDelay: `${i * 0.45}s`, zIndex: 5 - i }}
        >
          {i === 0 && (
            <>
              <p className="truncate font-serif text-[9px] font-semibold text-[#2a2238]">{file.name.replace(/\.[^.]+$/, "")}</p>
              <div className="mt-2 space-y-1.5">
                {[92, 100, 84, 97, 70, 100, 88, 60].map((w, k) => (
                  <div key={k} className="h-[3px] rounded-full bg-[rgb(42_34_56/0.25)]" style={{ width: `${w}%` }} />
                ))}
              </div>
            </>
          )}
        </div>
      ))}
    </div>
  );
}
