import { usePlayer } from "@/stores/player";
import { cn, formatClock } from "@/utils/format";

/**
 * Whole-book progress drawn from real chapter durations: one segment per chapter,
 * filled as it's listened to. Click a segment to jump there.
 */
export function BookTimeline() {
  const { playback, trackIndex, position, seekBook } = usePlayer();
  if (!playback || playback.total_duration <= 0) return null;
  const total = playback.total_duration;
  const at = (playback.tracks[trackIndex]?.offset ?? 0) + position;
  return (
    <div>
      <div className="flex h-8 items-end gap-[3px]" role="group" aria-label="Chapters timeline">
        {playback.tracks.map((t, i) => {
          const fill = i < trackIndex ? 1 : i > trackIndex ? 0 : Math.min(1, position / Math.max(t.duration, 0.001));
          const current = i === trackIndex;
          return (
            <button
              key={t.chapter_id}
              type="button"
              onClick={(e) => {
                const rect = e.currentTarget.getBoundingClientRect();
                const frac = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
                seekBook(t.offset + frac * t.duration);
              }}
              className="group relative h-full min-w-[4px] rounded-[3px]"
              style={{ flexGrow: Math.max(t.duration, 1) }}
              aria-label={`${t.title}, ${formatClock(t.duration)}`}
              title={t.title}
            >
              <span className={cn("absolute inset-x-0 bottom-0 overflow-hidden rounded-[3px] bg-white/[0.08] transition-all group-hover:bg-white/[0.14]", current ? "h-full" : "h-3 group-hover:h-5")}>
                <span className="absolute inset-y-0 left-0 bg-orchid-500" style={{ width: `${fill * 100}%` }} />
              </span>
            </button>
          );
        })}
      </div>
      <div className="mt-2 flex justify-between text-[11px] text-paper-500 tabular-nums">
        <span>Book {formatClock(at)}</span>
        <span>{formatClock(Math.max(0, total - at))} left in book</span>
      </div>
    </div>
  );
}
