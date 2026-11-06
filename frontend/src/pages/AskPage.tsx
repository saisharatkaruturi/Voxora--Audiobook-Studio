import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, BookOpenCheck, Brain, Cloud, Database, HardDrive, Loader2, Quote, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Notice, PageLoader, ProgressBar } from "@/components/ui/Feedback";
import { Textarea, Toggle } from "@/components/ui/Form";
import { toast } from "@/components/ui/Toast";
import { Insights } from "@/features/ask/Insights";
import { useBookContext } from "@/features/book/BookLayout";
import { useJob } from "@/hooks/useJob";
import { aiApi } from "@/services/api";
import { errorMessage } from "@/services/http";
import { qk } from "@/services/queryClient";
import type { ChatMessage } from "@/types/api";
import { cn } from "@/utils/format";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";

const SUGGESTIONS = ["What happened in the first chapter?", "Who are the main characters?", "What are the important events so far?", "Summarize the latest chapter I listened to."];

export default function AskPage() {
  const { book } = useBookContext();
  const qc = useQueryClient();
  useDocumentTitle("Ask the Book");
  const [question, setQuestion] = useState("");
  const [spoilerSafe, setSpoilerSafe] = useState(false);
  const [pending, setPending] = useState<{ jobId: string; question: string; since: number } | null>(null);
  const [indexJob, setIndexJob] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  const status = useQuery({ queryKey: qk.askStatus(book.id), queryFn: () => aiApi.askStatus(book.id) });
  // Poll while an answer is pending too, so a dropped WebSocket can never leave the page waiting.
  const chat = useQuery({ queryKey: qk.chat(book.id), queryFn: () => aiApi.chat(book.id), refetchInterval: pending ? 5000 : false });

  const index = useMutation({
    mutationFn: () => aiApi.index(book.id),
    onSuccess: (j) => setIndexJob(j.id),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const indexing = useJob(indexJob, (j) => {
    setIndexJob(null);
    if (j.status !== "completed") toast.error(j.error?.message ?? "Indexing failed.");
    void qc.invalidateQueries({ queryKey: qk.askStatus(book.id) });
  });

  // Keep an existing, still-running index job visible after a reload.
  useEffect(() => {
    const j = status.data?.index_job;
    if (j && (j.status === "queued" || j.status === "running") && !indexJob) setIndexJob(j.id);
  }, [status.data, indexJob]);

  const ask = useMutation({
    mutationFn: (q: string) => aiApi.ask(book.id, q, spoilerSafe),
    onSuccess: ({ job }, q) => {
      setPending({ jobId: job.id, question: q, since: Date.now() - 2000 });
      setQuestion("");
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const answering = useJob(pending?.jobId ?? null, (j) => {
    if (j.status !== "completed") toast.error(j.error?.message ?? "Couldn't answer that question.");
    void qc.invalidateQueries({ queryKey: qk.chat(book.id) }).then(() => setPending(null));
  });

  const clear = useMutation({
    mutationFn: () => aiApi.clearChat(book.id),
    onSuccess: () => qc.setQueryData(qk.chat(book.id), { items: [] }),
  });

  useEffect(() => {
    const last = chat.data?.items.at(-1);
    if (pending && last?.role === "assistant" && new Date(last.created_at).getTime() >= pending.since) setPending(null);
  }, [chat.data, pending]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [chat.data, pending]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const q = question.trim();
    if (q.length >= 2 && !pending) ask.mutate(q);
  };

  if (status.isPending) return <PageLoader label="Opening the book" />;
  if (status.isError) return <Notice kind="error">{errorMessage(status.error)}</Notice>;
  const s = status.data;
  const indexed = s.indexed_chunks > 0;
  const messages = chat.data?.items ?? [];

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_380px]">
      <section className="surface flex min-h-[70vh] flex-col overflow-hidden" aria-label="Ask the Book">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.05] px-5 py-4">
          <div>
            <h1 className="font-display text-2xl font-semibold tracking-tight text-paper-50">Ask the Book</h1>
            <p className="text-xs text-paper-500">Answers come only from this book's text, with the passages they're based on.</p>
          </div>
          {messages.length > 0 && (
            <Button size="sm" variant="ghost" icon={<Trash2 className="size-3.5" />} onClick={() => clear.mutate()}>
              Clear
            </Button>
          )}
        </header>

        <div className="flex-1 space-y-6 overflow-y-auto px-5 py-6" aria-live="polite">
          {!indexed ? (
            <div className="mx-auto max-w-md py-10 text-center">
              <Database className="mx-auto size-8 text-paper-400" />
              <h2 className="mt-4 font-display text-xl text-paper-50">Prepare this book for questions</h2>
              <p className="mt-2 text-sm text-paper-400">We split the text into passages and build a search index for this book only. Other books are never mixed in.</p>
              {indexing ? (
                <div className="mt-6 space-y-2 text-left">
                  <ProgressBar value={indexing.progress} label="Indexing progress" />
                  <p className="text-xs text-paper-500">{indexing.message}</p>
                </div>
              ) : (
                <Button variant="primary" className="mt-6" onClick={() => index.mutate()} loading={index.isPending || !!indexJob}>
                  Index this book
                </Button>
              )}
            </div>
          ) : messages.length === 0 && !pending ? (
            <div className="mx-auto max-w-lg py-8 text-center">
              <BookOpenCheck className="mx-auto size-8 text-orchid-400" />
              <p className="mt-4 text-paper-300">Ask about plot, characters, or any chapter.</p>
              <div className="mt-6 flex flex-wrap justify-center gap-2">
                {SUGGESTIONS.map((q) => (
                  <button key={q} type="button" onClick={() => ask.mutate(q)} className="rounded-full border border-white/[0.08] px-3.5 py-2 text-sm text-paper-300 hover:border-orchid-500/40 hover:text-paper-100">
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((m) => <Message key={m.id} message={m} />)
          )}
          {pending && !messages.some((m) => m.role === "user" && m.content === pending.question && messages.indexOf(m) === messages.length - 1) && (
            <div className="flex justify-end">
              <div className="max-w-[85%] rounded-2xl rounded-br-md bg-orchid-500/15 px-4 py-2.5 text-sm text-paper-50">{pending.question}</div>
            </div>
          )}
          {pending && (
            <div className="flex items-center gap-2 text-sm text-paper-400">
              <Loader2 className="size-4 animate-spin" />
              {answering?.message ?? "Reading the relevant passages…"}
              {s.llm.is_local && <span className="text-xs text-paper-500">(local models can take a minute)</span>}
            </div>
          )}
          <div ref={bottom} />
        </div>

        <form onSubmit={submit} className="border-t border-white/[0.05] p-4">
          <div className="relative">
            <Textarea
              rows={2}
              value={question}
              disabled={!indexed}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit();
                }
              }}
              placeholder={indexed ? "Who is… / What happened in chapter 5? / Why did…" : "Index the book first"}
              aria-label="Your question"
              maxLength={2000}
              className="resize-none pr-14"
            />
            <button
              type="submit"
              disabled={!indexed || question.trim().length < 2 || !!pending}
              className="absolute right-2.5 bottom-2.5 flex size-9 items-center justify-center rounded-full bg-orchid-500 text-ink-950 transition-opacity disabled:opacity-30"
              aria-label="Ask"
            >
              <ArrowUp className="size-4" />
            </button>
          </div>
          <div className="mt-3 max-w-sm">
            <Toggle checked={spoilerSafe} onChange={setSpoilerSafe} label="Spoiler-safe" description="Only use chapters up to where you've listened." />
          </div>
        </form>
      </section>

      <aside className="space-y-4">
        <div className="surface space-y-3 p-5 text-sm">
          <h2 className="font-medium text-paper-50">How answers are made</h2>
          <p className="flex gap-2 text-paper-400">
            <Database className="mt-0.5 size-4 shrink-0" /> {indexed ? `${s.indexed_chunks} passages indexed with ${s.embeddings}.` : "Not indexed yet."}
          </p>
          <p className="flex gap-2 text-paper-400">
            {s.llm.is_local ? <HardDrive className="mt-0.5 size-4 shrink-0 text-sage-400" /> : <Cloud className="mt-0.5 size-4 shrink-0 text-sky-400" />}
            {s.llm.available ? `${s.llm.name}${s.llm.model ? ` · ${s.llm.model}` : ""}${s.llm.is_local ? " (on this machine)" : " (cloud: passages are sent to the provider)"}` : `No AI model available${s.llm.reason ? `: ${s.llm.reason}` : ""}. You'll get the best-matching passages instead.`}
          </p>
          {indexed && (
            <Button size="sm" variant="ghost" onClick={() => index.mutate()} loading={!!indexJob}>
              Re-index after edits
            </Button>
          )}
        </div>
        <Insights bookId={book.id} llmAvailable={!!s.llm.available} />
      </aside>
    </div>
  );
}

function Message({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-orchid-500/15 px-4 py-2.5 text-sm text-paper-50">{message.content}</div>
      </div>
    );
  }
  const m = message.meta;
  const fromBook = m.from_book ?? message.content;
  return (
    <div className="max-w-[92%] animate-fade-up space-y-3">
      {m.mode === "passages_only" && m.notice && <Notice kind="info">{m.notice}</Notice>}
      <div className="rounded-2xl rounded-bl-md border border-white/[0.06] bg-white/[0.03] px-4 py-3">
        <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold tracking-wide text-sage-400 uppercase">
          <BookOpenCheck className="size-3.5" /> {m.found === false ? "Not found in the book" : "From the book"}
        </p>
        <p className="text-sm leading-relaxed whitespace-pre-line text-paper-100">{fromBook}</p>
        {m.inference && (
          <div className="mt-3 border-t border-white/[0.06] pt-3">
            <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold tracking-wide text-sky-400 uppercase">
              <Brain className="size-3.5" /> AI inference (not stated in the text)
            </p>
            <p className="text-sm leading-relaxed whitespace-pre-line text-paper-300">{m.inference}</p>
          </div>
        )}
      </div>
      {message.citations.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer list-none text-xs text-paper-400 hover:text-paper-200">
            <Quote className="mr-1 inline size-3" /> {message.citations.length} source passage{message.citations.length > 1 ? "s" : ""}: {[...new Set(message.citations.map((c) => c.chapter_title))].join(", ")}
          </summary>
          <ol className="mt-2 space-y-2">
            {message.citations.map((c) => (
              <li key={c.n} className={cn("rounded-xl border border-white/[0.05] bg-ink-900/60 p-3 text-xs")}>
                <p className="mb-1 font-medium text-paper-300">
                  [{c.n}] {c.chapter_title}
                </p>
                <p className="leading-relaxed text-paper-400">{c.excerpt}</p>
              </li>
            ))}
          </ol>
        </details>
      )}
      {m.model && <p className="text-[11px] text-paper-500">Answered by {m.model}</p>}
    </div>
  );
}
