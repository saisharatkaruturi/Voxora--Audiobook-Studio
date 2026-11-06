import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AudioLines, Eye, Pause, PenLine, Play, RotateCcw, Save, Scissors, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Badge, Notice, PageLoader, Spinner } from "@/components/ui/Feedback";
import { Field, Input, Select, Segmented, Textarea, Toggle } from "@/components/ui/Form";
import { toast } from "@/components/ui/Toast";
import { chaptersApi, voicesApi } from "@/services/api";
import { errorMessage } from "@/services/http";
import { qk } from "@/services/queryClient";
import type { Book, ChapterDetail } from "@/types/api";
import { CHAPTER_KINDS, cn, formatDuration, kindLabel } from "@/utils/format";

type Mode = "read" | "edit" | "narration";

export function ChapterPanel({ book, chapterId, onDeleted, onSplit }: { book: Book; chapterId: string; onDeleted: () => void; onSplit: (newId: string) => void }) {
  const qc = useQueryClient();
  const chapter = useQuery({ queryKey: qk.chapter(chapterId), queryFn: () => chaptersApi.get(chapterId) });
  const [mode, setMode] = useState<Mode>("read");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [dirty, setDirty] = useState(false);
  const [splitAt, setSplitAt] = useState<number | null>(null);
  const [splitTitle, setSplitTitle] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    if (chapter.data) {
      setTitle(chapter.data.title);
      setText(joinParagraphs(chapter.data));
      setDirty(false);
    }
  }, [chapter.data]);

  useEffect(() => {
    setMode("read");
  }, [chapterId]);

  const refresh = (data?: ChapterDetail) => {
    if (data) qc.setQueryData(qk.chapter(chapterId), data);
    void qc.invalidateQueries({ queryKey: qk.chapters(book.id) });
    void qc.invalidateQueries({ queryKey: qk.book(book.id) });
  };

  const save = useMutation({
    mutationFn: (body: Parameters<typeof chaptersApi.update>[1]) => chaptersApi.update(chapterId, body),
    onSuccess: (data) => {
      refresh(data);
      setDirty(false);
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const split = useMutation({
    mutationFn: () => chaptersApi.split(chapterId, splitAt!, splitTitle.trim() || undefined),
    onSuccess: ({ chapter_id }) => {
      toast.success("Chapter split in two.");
      setSplitAt(null);
      setSplitTitle("");
      void qc.invalidateQueries({ queryKey: qk.chapter(chapterId) });
      refresh();
      onSplit(chapter_id);
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const remove = useMutation({
    mutationFn: () => chaptersApi.remove(chapterId),
    onSuccess: () => {
      toast.success("Chapter deleted.");
      setConfirmDelete(false);
      refresh();
      onDeleted();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const regenerate = useMutation({
    mutationFn: () => chaptersApi.generate(chapterId),
    onSuccess: () => {
      toast.info("Generating this chapter. Other chapters are untouched.");
      refresh();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  if (chapter.isPending) return <PageLoader label="Loading chapter" />;
  if (chapter.isError) return <Notice kind="error">{errorMessage(chapter.error)}</Notice>;
  const c = chapter.data;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="space-y-4 border-b border-white/[0.05] p-5">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-60 flex-1">
            <label htmlFor="ch-title" className="sr-only">
              Chapter title
            </label>
            <Input
              id="ch-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onBlur={() => title.trim() && title.trim() !== c.title && save.mutate({ title: title.trim() })}
              onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
              className="h-11 font-serif text-lg"
              maxLength={500}
            />
          </div>
          <div className="w-40">
            <label htmlFor="ch-kind" className="sr-only">
              Section type
            </label>
            <Select id="ch-kind" value={c.kind} onChange={(e) => save.mutate({ kind: e.target.value })}>
              {CHAPTER_KINDS.map((k) => (
                <option key={k} value={k}>
                  {kindLabel(k)}
                </option>
              ))}
            </Select>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
          <div className="w-64">
            <Toggle checked={c.include_in_audio} onChange={(v) => save.mutate({ include_in_audio: v })} label="Include in audiobook" />
          </div>
          <div className="flex flex-wrap gap-1.5 text-xs text-paper-500">
            <Badge>{c.word_count.toLocaleString()} words</Badge>
            {c.pages && <Badge>{c.pages[0] === c.pages[1] ? `Page ${c.pages[0]}` : `Pages ${c.pages[0]}–${c.pages[1]}`}</Badge>}
            {c.language && <Badge>{c.language.toUpperCase()}</Badge>}
            {c.detection?.method && <Badge tone="sky">Detected by {String(c.detection.method).replace(/_/g, " ")}</Badge>}
            {c.audio_status === "done" && <Badge tone={c.stale ? "amber" : "sage"}>{c.stale ? "Audio outdated" : `Audio ${formatDuration(c.duration)}`}</Badge>}
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Segmented<Mode>
            label="Chapter view"
            value={mode}
            onChange={setMode}
            options={[
              { value: "read", label: <span className="inline-flex items-center gap-1.5"><Eye className="size-3.5" /> Read & split</span> },
              { value: "edit", label: <span className="inline-flex items-center gap-1.5"><PenLine className="size-3.5" /> Edit text</span> },
              { value: "narration", label: <span className="inline-flex items-center gap-1.5"><AudioLines className="size-3.5" /> As spoken</span> },
            ]}
          />
          <div className="flex flex-wrap gap-1.5">
            <PreviewButton book={book} chapter={c} />
            {(book.status === "ready" || book.status === "review") && c.include_in_audio && (
              <Button size="sm" icon={<RotateCcw className="size-3.5" />} onClick={() => regenerate.mutate()} loading={regenerate.isPending}>
                {c.audio_status === "done" ? "Regenerate" : "Generate"}
              </Button>
            )}
            <Button size="sm" variant="danger" icon={<Trash2 className="size-3.5" />} onClick={() => setConfirmDelete(true)}>
              Delete
            </Button>
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-5 sm:p-8">
        {mode === "read" && (
          <article className="mx-auto max-w-2xl space-y-5">
            {c.paragraphs.map((p, i) => (
              <div key={p.id} className="group relative">
                {i > 0 && (
                  <button
                    type="button"
                    onClick={() => setSplitAt(i)}
                    className="absolute -top-4 left-1/2 z-10 inline-flex -translate-x-1/2 items-center gap-1 rounded-full border border-white/[0.1] bg-ink-800 px-2.5 py-1 text-[11px] text-paper-300 opacity-0 shadow-lg transition-opacity group-hover:opacity-100 focus-visible:opacity-100 hover:text-orchid-300"
                    aria-label={`Split chapter before paragraph ${i + 1}`}
                  >
                    <Scissors className="size-3" /> Split here
                  </button>
                )}
                {p.kind === "heading" ? (
                  <h3 className="font-serif text-2xl text-paper-50">{p.text}</h3>
                ) : (
                  <p className="reading whitespace-pre-line">{p.text}</p>
                )}
              </div>
            ))}
            {c.paragraphs.length === 0 && <p className="text-sm text-paper-500">This chapter has no text.</p>}
          </article>
        )}
        {mode === "edit" && (
          <div className="mx-auto flex h-full max-w-3xl flex-col gap-3">
            <p className="text-xs text-paper-500">Separate paragraphs with a blank line. Editing changes what is narrated; the original file is never modified.</p>
            <Textarea
              aria-label="Chapter text"
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                setDirty(true);
              }}
              className="min-h-[50vh] flex-1 font-serif text-[15px] leading-relaxed"
              spellCheck
            />
            <div className="flex items-center justify-end gap-2">
              {dirty && <span className="mr-auto text-xs text-orchid-400">Unsaved changes</span>}
              <Button variant="ghost" disabled={!dirty} onClick={() => { setText(joinParagraphs(c)); setDirty(false); }}>
                Discard
              </Button>
              <Button variant="primary" icon={<Save className="size-4" />} disabled={!dirty || !text.trim()} loading={save.isPending} onClick={() => save.mutate({ text })}>
                Save text
              </Button>
            </div>
          </div>
        )}
        {mode === "narration" && <NarrationPreview chapterId={chapterId} version={c.text_version} />}
      </div>

      <Dialog
        open={splitAt !== null}
        onClose={() => setSplitAt(null)}
        title="Split chapter"
        description="Everything from this paragraph onward becomes a new chapter right after this one."
        footer={
          <>
            <Button variant="ghost" onClick={() => setSplitAt(null)}>Cancel</Button>
            <Button variant="primary" icon={<Scissors className="size-4" />} loading={split.isPending} onClick={() => split.mutate()}>Split</Button>
          </>
        }
      >
        {splitAt !== null && c.paragraphs[splitAt] && (
          <blockquote className="mb-4 line-clamp-3 border-l-2 border-orchid-500/60 pl-3 font-serif text-sm text-paper-300">{c.paragraphs[splitAt].text}</blockquote>
        )}
        <Field label="New chapter title" htmlFor="split-title" hint="Leave empty to use the paragraph if it looks like a heading.">
          <Input id="split-title" value={splitTitle} onChange={(e) => setSplitTitle(e.target.value)} maxLength={500} />
        </Field>
      </Dialog>

      <Dialog
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title={`Delete "${c.title}"?`}
        description="Its text and any generated audio are removed from this book. The original upload is not changed."
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmDelete(false)}>Cancel</Button>
            <Button variant="danger" loading={remove.isPending} onClick={() => remove.mutate()}>Delete chapter</Button>
          </>
        }
      />
    </div>
  );
}

function joinParagraphs(c: ChapterDetail): string {
  return c.paragraphs.map((p) => p.text).join("\n\n");
}

function NarrationPreview({ chapterId, version }: { chapterId: string; version: number }) {
  const q = useQuery({ queryKey: ["narration-preview", chapterId, version], queryFn: () => chaptersApi.narrationPreview(chapterId) });
  if (q.isPending) return <PageLoader label="Preparing narration script" />;
  if (q.isError) return <Notice kind="error">{errorMessage(q.error)}</Notice>;
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <Notice kind="info" title="Exactly what the narrator will say">
        With Narration Cleanup on, abbreviations, numbers, dates, symbols and URLs are written out for speech. Wording is never paraphrased.
      </Notice>
      {q.data.warnings.map((w, i) => (
        <Notice key={i} kind="warning">{w}</Notice>
      ))}
      <ol className="space-y-2">
        {q.data.chunks.map((ch, i) => (
          <li key={i} className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-3">
            <div className="mb-1 flex flex-wrap gap-1.5 text-[11px] text-paper-500">
              <span>¶ {ch.paragraph + 1}</span>
              <span>·</span>
              <span>{ch.voice}</span>
              {ch.speaker && <Badge tone="amber">{ch.speaker}</Badge>}
            </div>
            <p className="text-sm leading-relaxed text-paper-200">{ch.text}</p>
          </li>
        ))}
      </ol>
      <p className="text-xs text-paper-500">{q.data.characters.toLocaleString()} characters will be synthesized.</p>
    </div>
  );
}

/** Hear the start of this chapter in the book's current narrator voice. */
function PreviewButton({ book, chapter }: { book: Book; chapter: ChapterDetail }) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState(false);
  const preview = useMutation({
    mutationFn: () => {
      const first = chapter.paragraphs.find((p) => p.kind === "text") ?? chapter.paragraphs[0];
      if (!book.narration.voice_id) throw new Error("Choose a narrator in Voice Studio first.");
      if (!first) throw new Error("This chapter has no text to preview.");
      const text = first.text.length > 380 ? first.text.slice(0, 380).replace(/\s+\S*$/, "") + "." : first.text;
      return voicesApi.preview({ provider: book.narration.provider, voice_id: book.narration.voice_id, speed: book.narration.speed, pitch: book.narration.pitch, text, language: first.language ?? book.language });
    },
    onSuccess: ({ url }) => {
      audio.current?.pause();
      const a = new Audio(url);
      audio.current = a;
      a.onended = () => setPlaying(false);
      void a.play().then(() => setPlaying(true)).catch(() => toast.error("The browser blocked playback. Press preview again."));
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  useEffect(() => () => audio.current?.pause(), []);
  return (
    <Button
      size="sm"
      icon={preview.isPending ? <Spinner className="size-3.5" /> : playing ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
      onClick={() => {
        if (playing) {
          audio.current?.pause();
          setPlaying(false);
        } else preview.mutate();
      }}
      className={cn(playing && "text-orchid-300")}
    >
      {preview.isPending ? "Synthesizing…" : playing ? "Stop" : "Preview"}
    </Button>
  );
}
