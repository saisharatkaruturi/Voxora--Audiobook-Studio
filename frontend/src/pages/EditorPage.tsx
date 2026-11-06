import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Mic2, Plus, Sparkles } from "lucide-react";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { EmptyState, Notice, PageLoader } from "@/components/ui/Feedback";
import { Field, Input, Textarea } from "@/components/ui/Form";
import { toast } from "@/components/ui/Toast";
import { useBookContext } from "@/features/book/BookLayout";
import { ChapterList } from "@/features/editor/ChapterList";
import { ChapterPanel } from "@/features/editor/ChapterPanel";
import { booksApi, chaptersApi } from "@/services/api";
import { errorMessage } from "@/services/http";
import { qk } from "@/services/queryClient";
import type { Chapter } from "@/types/api";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";

export default function EditorPage() {
  const { book } = useBookContext();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const chapters = useQuery({ queryKey: qk.chapters(book.id), queryFn: () => chaptersApi.list(book.id) });
  const [selected, setSelected] = useState<string | null>(null);
  useDocumentTitle("Book Studio");
  const [adding, setAdding] = useState(false);
  const [meta, setMeta] = useState({ title: book.title, author: book.author ?? "" });

  const items = chapters.data?.items ?? [];
  useEffect(() => {
    if (items.length && (!selected || !items.some((c) => c.id === selected))) {
      setSelected((items.find((c) => c.kind === "chapter") ?? items[0]).id);
    }
  }, [items, selected]);

  const setList = (list: Chapter[]) => qc.setQueryData(qk.chapters(book.id), { items: list });

  const reorder = useMutation({
    mutationFn: (ids: string[]) => chaptersApi.reorder(book.id, ids),
    onMutate: (ids) => {
      const prev = items;
      setList(ids.map((id) => items.find((c) => c.id === id)!).map((c, i) => ({ ...c, position: i })));
      return { prev };
    },
    onSuccess: (data) => setList(data.items),
    onError: (e, _v, ctx) => {
      if (ctx) setList(ctx.prev);
      toast.error(errorMessage(e));
    },
  });

  const merge = useMutation({
    mutationFn: (ids: string[]) => chaptersApi.merge(book.id, ids),
    onSuccess: ({ chapter_id }) => {
      toast.success("Chapters merged.");
      setSelected(chapter_id);
      void qc.invalidateQueries({ queryKey: qk.chapters(book.id) });
      void qc.invalidateQueries({ queryKey: qk.chapter(chapter_id) });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const saveMeta = useMutation({
    mutationFn: () => booksApi.update(book.id, { title: meta.title.trim(), author: meta.author.trim() || null }),
    onSuccess: (b) => {
      qc.setQueryData(qk.book(book.id), b);
      toast.success("Book details saved.");
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  if (book.status === "analyzing" || book.status === "uploaded") {
    return (
      <EmptyState icon={<Sparkles className="size-6" />} title="Still reading the pages" action={<ButtonLink to={`/books/${book.id}/processing`}>See progress</ButtonLink>}>
        The editor opens once text extraction and chapter detection finish.
      </EmptyState>
    );
  }
  if (chapters.isPending) return <PageLoader label="Finding the chapters" />;
  if (chapters.isError) return <Notice kind="error">{errorMessage(chapters.error)}</Notice>;

  const metaDirty = meta.title.trim() !== book.title || (meta.author.trim() || null) !== (book.author || null);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight text-paper-50">Book Studio</h1>
          <p className="mt-1 text-sm text-paper-400">Extraction is never perfect. Fix chapters here before narrating: rename, reorder, merge, split, or edit text.</p>
        </div>
        <div className="flex gap-2">
          <Button icon={<Plus className="size-4" />} onClick={() => setAdding(true)}>
            Add chapter
          </Button>
          <Button variant="primary" icon={<Mic2 className="size-4" />} onClick={() => navigate(`/books/${book.id}/voice`)}>
            Choose narrator
          </Button>
        </div>
      </div>

      <form
        className="surface flex flex-wrap items-end gap-3 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (meta.title.trim()) saveMeta.mutate();
        }}
      >
        <div className="min-w-56 flex-[2]">
          <Field label="Title" htmlFor="b-title">
            <Input id="b-title" value={meta.title} onChange={(e) => setMeta({ ...meta, title: e.target.value })} maxLength={500} required />
          </Field>
        </div>
        <div className="min-w-44 flex-1">
          <Field label="Author" htmlFor="b-author">
            <Input id="b-author" value={meta.author} onChange={(e) => setMeta({ ...meta, author: e.target.value })} maxLength={300} placeholder="Unknown" />
          </Field>
        </div>
        <Button type="submit" disabled={!metaDirty || !meta.title.trim()} loading={saveMeta.isPending}>
          Save details
        </Button>
      </form>

      <div className="surface grid overflow-hidden lg:h-[calc(100dvh-230px)] lg:min-h-[560px] lg:grid-cols-[300px_1fr]">
        <div className="max-h-[45vh] border-b border-white/[0.05] lg:max-h-none lg:border-r lg:border-b-0">
          <ChapterList
            chapters={items}
            selectedId={selected}
            onSelect={setSelected}
            onReorder={(ids) => reorder.mutate(ids)}
            onMerge={(ids) => merge.mutate(ids)}
            busy={reorder.isPending || merge.isPending}
          />
        </div>
        <div className="min-h-[60vh] lg:min-h-0">
          {selected ? (
            <ChapterPanel key={selected} book={book} chapterId={selected} onDeleted={() => setSelected(null)} onSplit={(id) => setSelected(id)} />
          ) : (
            <p className="p-8 text-sm text-paper-500">Select a chapter.</p>
          )}
        </div>
      </div>

      <AddChapterDialog open={adding} onClose={() => setAdding(false)} bookId={book.id} afterPosition={items.find((c) => c.id === selected)?.position ?? null} onCreated={setSelected} />
    </div>
  );
}

function AddChapterDialog({ open, onClose, bookId, afterPosition, onCreated }: { open: boolean; onClose: () => void; bookId: string; afterPosition: number | null; onCreated: (id: string) => void }) {
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const create = useMutation({
    mutationFn: () => chaptersApi.create(bookId, { title: title.trim(), text, after_position: afterPosition }),
    onSuccess: (c) => {
      void qc.invalidateQueries({ queryKey: qk.chapters(bookId) });
      onCreated(c.id);
      setTitle("");
      setText("");
      onClose();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Add a chapter"
      description="Inserted after the selected chapter."
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!title.trim() || !text.trim()} loading={create.isPending} onClick={() => create.mutate()}>
            Add chapter
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Title" htmlFor="new-title">
          <Input id="new-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={500} />
        </Field>
        <Field label="Text" htmlFor="new-text" hint="Separate paragraphs with a blank line.">
          <Textarea id="new-text" rows={10} value={text} onChange={(e) => setText(e.target.value)} />
        </Field>
      </div>
    </Dialog>
  );
}
