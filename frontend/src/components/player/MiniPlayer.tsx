import { Link, useLocation } from "react-router-dom";
import { Pause, Play, RotateCcw, RotateCw, X } from "lucide-react";
import { BookCover } from "@/components/book/BookCover";
import { IconButton } from "@/components/ui/Button";
import { usePlayer } from "@/stores/player";
import { formatClock } from "@/utils/format";
import { SpeedControl, SleepControl, VolumeControl } from "@/components/player/Controls";

/** Persistent bottom bar shown whenever a book is loaded and the full player isn't open. */
export function MiniPlayer() {
  const { playback, trackIndex, playing, position, duration, toggle, skip, close, bookId } = usePlayer();
  const { pathname } = useLocation();
  if (!playback || !bookId || pathname === `/books/${bookId}/listen`) return null;
  const track = playback.tracks[trackIndex];
  const pct = duration ? (position / duration) * 100 : 0;
  return (
    <div className="fixed inset-x-0 bottom-[calc(64px+env(safe-area-inset-bottom))] z-40 px-2 md:bottom-4 md:px-4">
      <div className="glass relative mx-auto flex max-w-5xl items-center gap-3 overflow-hidden rounded-2xl py-2 pr-2 pl-2 shadow-2xl" role="region" aria-label="Now playing">
        <div className="absolute inset-x-0 top-0 h-0.5 bg-white/[0.06]">
          <div className="h-full bg-orchid-500 transition-[width] duration-300" style={{ width: `${pct}%` }} />
        </div>
        <Link to={`/books/${bookId}/listen`} className="flex min-w-0 flex-1 items-center gap-3 rounded-xl" aria-label="Open full player">
          <BookCover url={playback.book.cover_url} title={playback.book.title} size="sm" className="w-10 shrink-0" />
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-paper-50">{playback.book.title}</p>
            <p className="truncate text-xs text-paper-400">
              {track?.title} · <span className="tabular-nums">{formatClock(position)}</span>
            </p>
          </div>
        </Link>
        <div className="flex items-center gap-0.5">
          <IconButton label="Back 15 seconds" onClick={() => skip(-15)} className="max-sm:hidden">
            <RotateCcw className="size-4" />
          </IconButton>
          <IconButton label={playing ? "Pause" : "Play"} variant="primary" onClick={toggle}>
            {playing ? <Pause className="size-4 fill-current" /> : <Play className="size-4 translate-x-px fill-current" />}
          </IconButton>
          <IconButton label="Forward 30 seconds" onClick={() => skip(30)} className="max-sm:hidden">
            <RotateCw className="size-4" />
          </IconButton>
          <div className="hidden items-center lg:flex">
            <SpeedControl />
            <SleepControl />
            <VolumeControl />
          </div>
          <span className="hidden px-2 text-xs text-paper-500 tabular-nums xl:inline">-{formatClock(Math.max(0, duration - position))}</span>
          <IconButton label="Close player" size="sm" onClick={close}>
            <X className="size-4" />
          </IconButton>
        </div>
      </div>
    </div>
  );
}
