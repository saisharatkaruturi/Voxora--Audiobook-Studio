import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileArchive, FileAudio, FileText, ImagePlus, PenLine, Play, RefreshCw, RotateCcw, Trash2, Wand2 } from "lucide-react";
import { BookCover } from "@/components/book/BookCover";
import { StatusBadge } from "@/components/book/StatusBadge";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Notice, ProgressBar, Skeleton } from "@/components/ui/Feedback";
import { toast } from "@/components/ui/Toast";
import { useBookContext } from "@/features/book/BookLayout";
import { booksApi, playerApi } from "@/services/api";
import { bookAudio, deleteBookAudio, deviceDelivery, saveBookAsFile, storageEstimate, syncBook, trackKey } from "@/services/deviceAudio";
import { downloadAuthenticated, errorMessage } from "@/services/http";
import { qk } from "@/services/queryClient";
import { usePlayer } from "@/stores/player";
import { useJob } from "@/hooks/useJob";
import type { DownloadItem } from "@/types/api";
import { bookFraction, formatBytes, formatClock, formatDuration, formatNumber } from "@/utils/format";
import { languageName } from "@/utils/languages";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { BrandBadge } from "@/components/brand/BrandWordmark";

export default function BookDetailsPage() {
  const { book } = useBookContext();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const player = usePlayer();
  const coverInput = useRef<HTMLInputElement>(null);
  useDocumentTitle(book.title);
  const [confirm, setConfirm] = useState<null | "book" | "audio" | "original" | "regenerate">(null);

  const hasAudio = (book.chapters_with_audio ?? 0) > 0;
  const fraction = bookFraction(book.progress?.book_position_seconds, book.total_duration);
  const inProgress = !!book.progress && !book.progress.completed && (book.progress.book_position_seconds ?? 0) > 1;

  const listen = async (fromStart: boolean) => {
    try {
      await player.load(book.id, fromStart ? { chapterId: null, position: 0, autoplay: true } : { autoplay: true });
      navigate(`/books/${book.id}/listen`);
    } catch (e) {
      toast.error(errorMessage(e));
    }
  };

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: qk.book(book.id) });
    void qc.invalidateQueries({ queryKey: ["books"] });
    void qc.invalidateQueries({ queryKey: qk.downloads(book.id) });
  };

  const cover = useMutation({
    mutationFn: (file: File | null) => (file ? booksApi.uploadCover(book.id, file) : booksApi.generateCover(book.id)),
    onSuccess: (b) => {
      qc.setQueryData(qk.book(book.id), b);
      toast.success("Cover updated.");
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const destroy = useMutation({
    mutationFn: async (what: "book" | "audio" | "original" | "regenerate") => {
      if (what === "book") {
        await booksApi.remove(book.id);
        return deleteBookAudio(book.id); // and its audio on this device
      }
      if (what === "audio") {
        const r = await booksApi.removeAudio(book.id);
        await deleteBookAudio(book.id);
        return r;
      }
      if (what === "original") return booksApi.removeOriginal(book.id);
      return booksApi.generate(book.id, { force: true });
    },
    onSuccess: (_d, what) => {
      setConfirm(null);
      if (what === "book") {
        if (player.bookId === book.id) player.close();
        toast.success("Book deleted, including its files and audio.");
        void qc.invalidateQueries({ queryKey: ["books"] });
        navigate("/library");
        return;
      }
      if (what === "audio" && player.bookId === book.id) player.close();
      if (what === "regenerate") {
        navigate(`/books/${book.id}/processing`);
      } else toast.success(what === "audio" ? "Generated audio deleted." : "Original upload deleted. Extracted text is kept.");
      refresh();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  return (
    <div className="space-y-10">
      <section className="grid gap-8 md:grid-cols-[260px_1fr] md:gap-12">
        <div className="relative mx-auto w-52 md:w-full">
          <BookCover url={book.cover_url} title={book.title} author={book.author} size="lg" />
          <div className="mt-3 flex justify-center gap-1">
            <Button size="sm" variant="ghost" icon={<ImagePlus className="size-3.5" />} onClick={() => coverInput.current?.click()} loading={cover.isPending && cover.variables !== null}>
              Upload cover
            </Button>
            <Button size="sm" variant="ghost" icon={<Wand2 className="size-3.5" />} onClick={() => cover.mutate(null)} loading={cover.isPending && cover.variables === null}>
              Generate
            </Button>
            <input
              ref={coverInput}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="sr-only"
              aria-label="Upload a cover image"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) cover.mutate(f);
                e.target.value = "";
              }}
            />
          </div>
        </div>

        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <BrandBadge />
            <StatusBadge status={book.status} paused={book.active_job?.status === "paused"} />
          </div>
          <h1 className="mt-4 font-display text-4xl leading-tight font-semibold tracking-tight text-paper-50 sm:text-5xl">{book.title}</h1>
          {book.subtitle && <p className="mt-2 text-lg text-paper-300">{book.subtitle}</p>}
          <p className="mt-3 text-paper-300">
            {book.author ? <>by <span className="text-paper-100">{book.author}</span></> : "Unknown author"}
            {book.narrator && <span className="text-paper-400"> · Narrated by {book.narrator}</span>}
          </p>
          {(book.series || book.genres?.length > 0) && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {book.series && (
                <Link to={`/library?group=series`} className="rounded-full border border-orchid-500/40 bg-orchid-500/10 px-3 py-1 text-xs font-medium text-orchid-300 hover:bg-orchid-500/20">
                  {book.series}
                  {book.series_index != null && ` · Book ${Number.isInteger(book.series_index) ? book.series_index : book.series_index.toFixed(1)}`}
                </Link>
              )}
              {book.genres?.map((g) => (
                <span key={g} className="rounded-full bg-white/[0.06] px-3 py-1 text-xs text-paper-300">
                  {g}
                </span>
              ))}
            </div>
          )}

          <dl className="mt-7 grid max-w-2xl grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
            <Stat label="Chapters" value={book.narrated_chapters ?? book.chapter_count ?? "—"} />
            <Stat label="Duration" value={hasAudio ? formatDuration(book.total_duration) : "—"} />
            <Stat label="Words" value={formatNumber(book.word_count)} />
            <Stat label="Language" value={book.languages.length > 1 ? `${languageName(book.language)} +${book.languages.length - 1}` : languageName(book.language)} />
          </dl>

          {hasAudio && fraction > 0 && (
            <div className="mt-7 max-w-md">
              <div className="mb-2 flex justify-between text-xs text-paper-400">
                <span>{book.progress?.completed ? "Finished" : `${Math.round(fraction * 100)}% listened`}</span>
                <span className="tabular-nums">{formatClock(book.progress?.book_position_seconds)} / {formatClock(book.total_duration)}</span>
              </div>
              <ProgressBar value={fraction * 100} label="Listening progress" />
            </div>
          )}

          <div className="mt-8 flex flex-wrap gap-2">
            {hasAudio ? (
              <>
                <Button variant="primary" size="lg" icon={<Play className="size-4 fill-current" />} onClick={() => void listen(false)}>
                  {inProgress ? "Continue listening" : "Play"}
                </Button>
                {inProgress && (
                  <Button size="lg" icon={<RotateCcw className="size-4" />} onClick={() => void listen(true)}>
                    Play from beginning
                  </Button>
                )}
              </>
            ) : book.status === "review" ? (
              <ButtonLink to="voice" variant="primary" size="lg">
                Choose narrator & create
              </ButtonLink>
            ) : null}
            <ButtonLink to="edit" size="lg" icon={<PenLine className="size-4" />}>
              Edit book
            </ButtonLink>
            {hasAudio && (
              <Button size="lg" icon={<RefreshCw className="size-4" />} onClick={() => setConfirm("regenerate")} disabled={book.status === "generating"}>
                Regenerate
              </Button>
            )}
            <Button size="lg" variant="ghost" icon={<Download className="size-4" />} onClick={() => document.getElementById("downloads")?.scrollIntoView({ behavior: "smooth" })}>
              Download
            </Button>
          </div>

          {book.error && book.status !== "analyzing" && book.status !== "generating" && (
            <Notice kind="warning" className="mt-6 max-w-2xl" title="Needs attention">
              {book.error.message}
            </Notice>
          )}
          {book.description && <p className="mt-8 max-w-2xl leading-relaxed text-paper-300">{book.description}</p>}
        </div>
      </section>

      <OnThisDevice bookId={book.id} onRecreate={() => setConfirm("regenerate")} />
      <Downloads bookId={book.id} />

      <section className="surface p-6" aria-labelledby="privacy">
        <h2 id="privacy" className="font-display text-xl text-paper-50">
          Your data
        </h2>
        <p className="mt-1 max-w-2xl text-sm text-paper-400">
          The original upload, extracted text and generated audio are stored until you delete them. Deleting is permanent.
        </p>
        <div className="mt-5 flex flex-wrap gap-2">
          <Button variant="danger" icon={<FileAudio className="size-4" />} onClick={() => setConfirm("audio")} disabled={!hasAudio}>
            Delete audio
          </Button>
          <Button variant="danger" icon={<FileText className="size-4" />} onClick={() => setConfirm("original")}>
            Delete original file
          </Button>
          <Button variant="danger" icon={<Trash2 className="size-4" />} onClick={() => setConfirm("book")}>
            Delete book
          </Button>
        </div>
      </section>

      <Dialog
        open={confirm !== null}
        onClose={() => setConfirm(null)}
        size="sm"
        title={
          confirm === "book"
            ? "Delete this book?"
            : confirm === "audio"
              ? "Delete generated audio?"
              : confirm === "original"
                ? "Delete the original file?"
                : "Regenerate all audio?"
        }
        description={
          confirm === "book"
            ? "Removes the upload, text, audio, bookmarks, chat and listening progress."
            : confirm === "audio"
              ? "Chapter files and the full audiobook are removed. Your text and edits stay, so you can generate again."
              : confirm === "original"
                ? "The extracted text and audio are kept, but the book can't be re-analyzed from scratch."
                : "Every chapter is synthesized again with the current voice settings, even unchanged ones."
        }
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirm(null)}>
              Cancel
            </Button>
            <Button variant={confirm === "regenerate" ? "primary" : "danger"} loading={destroy.isPending} onClick={() => confirm && destroy.mutate(confirm)}>
              {confirm === "regenerate" ? "Regenerate" : "Delete"}
            </Button>
          </>
        }
      />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-paper-500">{label}</dt>
      <dd className="mt-0.5 text-lg text-paper-100 tabular-nums">{value}</dd>
    </div>
  );
}

const ICONS: Record<DownloadItem["kind"], typeof FileAudio> = {
  full: FileAudio,
  chapter: FileAudio,
  extracted_text: FileText,
  processed_text: FileText,
  narration_text: FileText,
  original: FileText,
  zip: FileArchive,
  m4b: FileAudio,
};

/** Device delivery: what of this audiobook is saved in this browser, and saving it as one file. */
function OnThisDevice({ bookId, onRecreate }: { bookId: string; onRecreate: () => void }) {
  const status = useQuery({
    queryKey: ["device-audio", bookId],
    queryFn: async () => {
      if (!(await deviceDelivery())) return null;
      const playback = await playerApi.playback(bookId);
      if (!playback.tracks.length) return null;
      await syncBook(bookId, playback).catch(() => undefined);
      const fresh = await playerApi.playback(bookId);
      const held = await bookAudio(bookId);
      const have = new Set(held.map((c) => `${c.chapterId}:${c.hash}`));
      const here = fresh.tracks.filter((t) => have.has(`${t.chapter_id}:${trackKey(t)}`)).length;
      const elsewhere = fresh.tracks.filter((t) => !have.has(`${t.chapter_id}:${trackKey(t)}`) && !t.url).length;
      return { playback: fresh, here, elsewhere, total: fresh.tracks.length, bytes: held.reduce((n, c) => n + c.size, 0), device: await storageEstimate() };
    },
    refetchInterval: (q) => (q.state.data && q.state.data.here + q.state.data.elsewhere < q.state.data.total ? 5000 : false),
  });
  const [saving, setSaving] = useState(false);
  const d = status.data;
  if (!d) return null;
  const complete = d.here === d.total;
  return (
    <section aria-labelledby="ondevice" className="scroll-mt-6">
      <h2 id="ondevice" className="font-display text-2xl text-paper-50">
        On this device
      </h2>
      <div className="surface mt-4 flex flex-col gap-4 p-5 sm:flex-row sm:items-center">
        <div className="min-w-0 flex-1">
          <p className="text-sm text-paper-100">
            {complete ? "The whole audiobook is saved on this device." : `${d.here} of ${d.total} chapters saved on this device${d.here + d.elsewhere < d.total ? ", more arriving as they finish" : ""}.`}
          </p>
          <p className="mt-0.5 text-xs text-paper-500">
            {formatBytes(d.bytes)} used · plays offline · not kept on the VOXORA server
            {d.device && d.device.quota ? ` · ${formatBytes(Math.max(0, d.device.quota - d.device.used))} free for audiobooks` : ""}
          </p>
          {d.elsewhere > 0 && (
            <Notice kind="info" className="mt-3" action={<Button size="sm" onClick={onRecreate}>Re-create audio here</Button>}>
              {d.elsewhere} {d.elsewhere === 1 ? "chapter is" : "chapters are"} saved on another device or browser, where this book was converted.
            </Notice>
          )}
        </div>
        <Button
          icon={<Download className="size-4" />}
          disabled={!complete}
          loading={saving}
          onClick={async () => {
            setSaving(true);
            try {
              await saveBookAsFile(d.playback);
            } catch (e) {
              toast.error(errorMessage(e));
            } finally {
              setSaving(false);
            }
          }}
        >
          Save as one file
        </Button>
      </div>
    </section>
  );
}

function Downloads({ bookId }: { bookId: string }) {
  const q = useQuery({ queryKey: qk.downloads(bookId), queryFn: () => booksApi.downloads(bookId) });
  const [busy, setBusy] = useState<string | null>(null);
  const [m4bJob, setM4bJob] = useState<string | null>(null);
  const building = useJob(m4bJob, (j) => {
    setM4bJob(null);
    if (j.status === "completed") toast.success("M4B audiobook ready, with chapters and cover.");
    else toast.error(j.error?.message ?? "Couldn't build the M4B.");
    void q.refetch();
  });
  const items = q.data?.items ?? [];
  const chapters = items.filter((i) => i.kind === "chapter");
  const others = items.filter((i) => i.kind !== "chapter");

  const get = async (item: DownloadItem) => {
    if (!item.url) {
      if (item.kind === "m4b") {
        try {
          setM4bJob((await booksApi.buildM4b(bookId)).id);
        } catch (e) {
          toast.error(errorMessage(e));
        }
      }
      return;
    }
    if (item.url.startsWith("/media/")) {
      window.location.href = item.url; // signed link with Content-Disposition: attachment
      return;
    }
    setBusy(item.kind);
    try {
      await downloadAuthenticated(item.url, item.kind === "zip" ? "audiobook.zip" : item.kind === "full" ? "audiobook.mp3" : "book.txt");
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section id="downloads" aria-labelledby="dl" className="scroll-mt-6">
      <h2 id="dl" className="font-display text-2xl text-paper-50">
        Downloads
      </h2>
      {q.isPending ? (
        <Skeleton className="mt-4 h-40" />
      ) : q.isError ? (
        <Notice kind="error" className="mt-4">{errorMessage(q.error)}</Notice>
      ) : (
        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <ul className="surface divide-y divide-white/[0.04] p-2">
            {others.map((item) => {
              const Icon = ICONS[item.kind];
              return (
                <li key={item.kind} className="flex items-center gap-3 px-3 py-3">
                  <Icon className="size-4 shrink-0 text-paper-400" aria-hidden />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-paper-100">{item.label}</p>
                    <p className="text-xs text-paper-500">
                      {item.kind === "m4b" && !item.url
                        ? m4bJob
                          ? `Encoding… ${building?.progress ? `${Math.round(building.progress)}%` : ""}`
                          : "Built on request, for Apple Books and audiobook apps"
                        : item.size
                          ? formatBytes(item.size)
                          : item.kind === "zip" || item.kind === "full"
                            ? "Built on request"
                            : "Plain text"}
                      {item.duration ? ` · ${formatDuration(item.duration)}` : ""}
                    </p>
                  </div>
                  <Button size="sm" icon={<Download className="size-3.5" />} loading={busy === item.kind || (item.kind === "m4b" && !!m4bJob)} onClick={() => void get(item)}>
                    {item.kind === "zip" ? "ZIP" : item.kind === "m4b" && !item.url ? "Build" : "Get"}
                  </Button>
                </li>
              );
            })}
          </ul>
          <div className="surface p-2">
            <p className="eyebrow px-3 pt-2 pb-1">Chapter files</p>
            {chapters.length === 0 ? (
              <p className="px-3 py-6 text-sm text-paper-500">No chapter audio yet.</p>
            ) : (
              <ul className="max-h-80 divide-y divide-white/[0.04] overflow-y-auto">
                {chapters.map((item) => (
                  <li key={item.chapter_id} className="flex items-center gap-3 px-3 py-2.5">
                    <p className="min-w-0 flex-1 truncate text-sm text-paper-200">{item.label}</p>
                    <span className="text-xs text-paper-500 tabular-nums">{formatDuration(item.duration)}</span>
                    <a href={item.url ?? undefined} className="rounded-lg p-1.5 text-paper-400 hover:bg-white/[0.06] hover:text-paper-100" aria-label={`Download ${item.label}`}>
                      <Download className="size-4" />
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
