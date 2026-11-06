import { useMutation } from "@tanstack/react-query";
import { Bookmark as BookmarkIcon, Play, Trash2, Volume2 } from "lucide-react";
import { toast } from "@/components/ui/Toast";
import { playerApi } from "@/services/api";
import { errorMessage } from "@/services/http";
import { usePlayer } from "@/stores/player";
import { cn, formatClock, relativeTime } from "@/utils/format";

export function ChaptersPanel() {
  const { playback, trackIndex, position, selectTrack, playing } = usePlayer();
  if (!playback) return null;
  return (
    <ol className="space-y-0.5" aria-label="Chapters">
      {playback.tracks.map((t, i) => {
        const current = i === trackIndex;
        const done = i < trackIndex;
        return (
          <li key={t.chapter_id}>
            <button
              type="button"
              onClick={() => selectTrack(i, 0, true)}
              aria-current={current ? "true" : undefined}
              className={cn("flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors", current ? "bg-white/[0.07]" : "hover:bg-white/[0.04]")}
            >
              <span className={cn("flex size-7 shrink-0 items-center justify-center rounded-full text-[11px] tabular-nums", current ? "bg-orchid-500 text-ink-950" : "bg-white/[0.05] text-paper-400")}>
                {current && playing ? <Volume2 className="size-3.5" /> : i + 1}
              </span>
              <span className="min-w-0 flex-1">
                <span className={cn("block truncate text-sm", current ? "font-medium text-paper-50" : done ? "text-paper-400" : "text-paper-200")}>{t.title}</span>
                {current && (
                  <span className="mt-1.5 block h-0.5 overflow-hidden rounded-full bg-white/[0.08]">
                    <span className="block h-full bg-orchid-500" style={{ width: `${(position / Math.max(t.duration, 1)) * 100}%` }} />
                  </span>
                )}
              </span>
              <span className="text-xs text-paper-500 tabular-nums">{formatClock(t.duration)}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

export function BookmarksPanel() {
  const { playback, selectTrack, refreshPlayback } = usePlayer();
  const remove = useMutation({
    mutationFn: (id: string) => playerApi.removeBookmark(id),
    onSuccess: () => void refreshPlayback(),
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (!playback) return null;
  if (!playback.bookmarks.length) {
    return (
      <div className="py-10 text-center">
        <BookmarkIcon className="mx-auto size-6 text-paper-500" />
        <p className="mt-3 text-sm text-paper-400">No bookmarks yet.</p>
        <p className="mt-1 text-xs text-paper-500">Use the bookmark button to save a moment, with an optional note.</p>
      </div>
    );
  }
  return (
    <ul className="space-y-2" aria-label="Bookmarks">
      {playback.bookmarks.map((b) => {
        const index = playback.tracks.findIndex((t) => t.chapter_id === b.chapter_id);
        return (
          <li key={b.id} className="group flex items-start gap-3 rounded-xl border border-white/[0.05] bg-white/[0.02] p-3">
            <button
              type="button"
              disabled={index < 0}
              onClick={() => selectTrack(index, b.position_seconds, true)}
              className="flex size-8 shrink-0 items-center justify-center rounded-full bg-white/[0.07] text-paper-100 hover:bg-orchid-500 hover:text-ink-950 disabled:opacity-40"
              aria-label={`Play from bookmark at ${formatClock(b.position_seconds)}`}
            >
              <Play className="size-3.5 translate-x-px fill-current" />
            </button>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm text-paper-100">{b.chapter_title ?? "Chapter"}</p>
              <p className="text-xs text-paper-400 tabular-nums">
                {formatClock(b.position_seconds)} · {relativeTime(b.created_at)}
              </p>
              {b.note && <p className="mt-1.5 text-sm text-paper-300">“{b.note}”</p>}
            </div>
            <button
              type="button"
              onClick={() => remove.mutate(b.id)}
              className="rounded-lg p-1.5 text-paper-500 opacity-0 group-hover:opacity-100 hover:text-rose-400 focus-visible:opacity-100"
              aria-label="Delete bookmark"
            >
              <Trash2 className="size-3.5" />
            </button>
          </li>
        );
      })}
    </ul>
  );
}
