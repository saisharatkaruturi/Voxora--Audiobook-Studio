import { useEffect, useRef, useState, type ReactNode } from "react";
import { Bookmark, Gauge, Loader2, Moon, Pause, Play, RotateCcw, RotateCw, SkipBack, SkipForward, Volume1, Volume2, VolumeX } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { IconButton } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Form";
import { Dialog } from "@/components/ui/Dialog";
import { Button } from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { playerApi } from "@/services/api";
import { errorMessage } from "@/services/http";
import { qk } from "@/services/queryClient";
import { SPEEDS, usePlayer, type SleepMode } from "@/stores/player";
import { cn, formatClock } from "@/utils/format";

export function TransportControls({ size = "lg" }: { size?: "md" | "lg" }) {
  const { playing, buffering, toggle, skip, next, previous, playback, trackIndex } = usePlayer();
  const hasNext = !!playback && trackIndex < playback.tracks.length - 1;
  const big = size === "lg";
  return (
    <div className={cn("flex items-center justify-center", big ? "gap-3 sm:gap-5" : "gap-1")}>
      <IconButton label="Previous chapter" size={big ? "lg" : "md"} onClick={previous}>
        <SkipBack className={big ? "size-6" : "size-5"} />
      </IconButton>
      <IconButton label="Back 15 seconds" size={big ? "lg" : "md"} onClick={() => skip(-15)}>
        <SkipLabel icon={<RotateCcw className={big ? "size-7" : "size-5"} strokeWidth={1.75} />} n={15} big={big} />
      </IconButton>
      <IconButton label={playing ? "Pause" : "Play"} variant="primary" size={big ? "xl" : "lg"} onClick={toggle} className={big ? "mx-1" : ""}>
        {buffering && playing ? (
          <Loader2 className={cn("animate-spin", big ? "size-7" : "size-5")} />
        ) : playing ? (
          <Pause className={cn("fill-current", big ? "size-7" : "size-5")} />
        ) : (
          <Play className={cn("translate-x-0.5 fill-current", big ? "size-7" : "size-5")} />
        )}
      </IconButton>
      <IconButton label="Forward 30 seconds" size={big ? "lg" : "md"} onClick={() => skip(30)}>
        <SkipLabel icon={<RotateCw className={big ? "size-7" : "size-5"} strokeWidth={1.75} />} n={30} big={big} />
      </IconButton>
      <IconButton label="Next chapter" size={big ? "lg" : "md"} onClick={next} disabled={!hasNext}>
        <SkipForward className={big ? "size-6" : "size-5"} />
      </IconButton>
    </div>
  );
}

function SkipLabel({ icon, n, big }: { icon: ReactNode; n: number; big: boolean }) {
  return (
    <span className="relative inline-flex items-center justify-center">
      {icon}
      <span className={cn("absolute font-semibold tabular-nums", big ? "text-[9px]" : "text-[7px]")}>{n}</span>
    </span>
  );
}

/** Chapter scrubber with elapsed / remaining time. Arrow keys seek 5s. */
export function Scrubber({ compact = false }: { compact?: boolean }) {
  const { position, duration, seek } = usePlayer();
  const [drag, setDrag] = useState<number | null>(null);
  const value = drag ?? position;
  const pct = duration ? (value / duration) * 100 : 0;
  return (
    <div className="w-full">
      <div className="group relative flex h-5 items-center">
        <div className="absolute inset-x-0 h-1.5 overflow-hidden rounded-full bg-white/[0.1]">
          <div className="h-full rounded-full bg-orchid-500" style={{ width: `${pct}%` }} />
        </div>
        <input
          type="range"
          min={0}
          max={duration || 0}
          step={0.1}
          value={value}
          aria-label="Seek within chapter"
          aria-valuetext={`${formatClock(value)} of ${formatClock(duration)}`}
          onChange={(e) => setDrag(Number(e.target.value))}
          onPointerUp={() => {
            if (drag !== null) seek(drag);
            setDrag(null);
          }}
          onKeyUp={() => {
            if (drag !== null) seek(drag);
            setDrag(null);
          }}
          className="absolute inset-0 w-full cursor-pointer opacity-0"
        />
        <div
          className="pointer-events-none absolute size-3.5 -translate-x-1/2 rounded-full bg-paper-50 shadow-md transition-transform group-hover:scale-110"
          style={{ left: `${pct}%` }}
        />
      </div>
      {!compact && (
        <div className="mt-1.5 flex justify-between text-xs text-paper-400 tabular-nums">
          <span>{formatClock(value)}</span>
          <span>-{formatClock(Math.max(0, duration - value))}</span>
        </div>
      )}
    </div>
  );
}

/** Small popover menu anchored to a trigger button. */
function Popover({ trigger, children, label }: { trigger: (open: boolean, toggle: () => void) => ReactNode; children: (close: () => void) => ReactNode; label: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return (
    <div ref={ref} className="relative">
      {trigger(open, () => setOpen((o) => !o))}
      {open && (
        <div role="menu" aria-label={label} className="glass absolute bottom-full left-1/2 z-50 mb-2 min-w-44 -translate-x-1/2 animate-fade-up rounded-2xl p-1.5 shadow-2xl">
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}

function MenuItem({ active, onClick, children }: { active?: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      role="menuitemradio"
      aria-checked={!!active}
      onClick={onClick}
      className={cn("flex w-full items-center justify-between gap-4 rounded-xl px-3 py-2 text-left text-sm", active ? "bg-white/[0.08] text-orchid-300" : "text-paper-200 hover:bg-white/[0.06]")}
    >
      {children}
    </button>
  );
}

function ToolButton({ label, active, onClick, children }: { label: string; active?: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-haspopup="menu"
      className={cn(
        "flex h-10 min-w-10 items-center justify-center gap-1.5 rounded-full px-3 text-[13px] font-medium transition-colors",
        active ? "bg-orchid-500/15 text-orchid-300" : "text-paper-300 hover:bg-white/[0.07] hover:text-paper-100",
      )}
    >
      {children}
    </button>
  );
}

export function SpeedControl() {
  const { rate, setRate } = usePlayer();
  return (
    <Popover
      label="Playback speed"
      trigger={(open, toggle) => (
        <ToolButton label={`Playback speed ${rate}x`} active={open || rate !== 1} onClick={toggle}>
          <Gauge className="size-4" />
          <span className="tabular-nums">{rate}×</span>
        </ToolButton>
      )}
    >
      {(close) =>
        SPEEDS.map((s) => (
          <MenuItem
            key={s}
            active={s === rate}
            onClick={() => {
              setRate(s);
              close();
            }}
          >
            <span className="tabular-nums">{s}×</span>
            {s === 1 && <span className="text-xs text-paper-500">Normal</span>}
          </MenuItem>
        ))
      }
    </Popover>
  );
}

const SLEEP_OPTIONS = [5, 10, 15, 30, 45, 60];

export function useSleepCountdown(): string | null {
  const sleep = usePlayer((s) => s.sleep);
  const [, tick] = useState(0);
  useEffect(() => {
    if (sleep.kind !== "timer") return;
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [sleep]);
  if (sleep.kind === "chapter") return "End of chapter";
  if (sleep.kind === "timer") return formatClock(Math.max(0, (sleep.endsAt - Date.now()) / 1000));
  return null;
}

export function SleepControl() {
  const { sleep, setSleep } = usePlayer();
  const countdown = useSleepCountdown();
  const choose = (mode: SleepMode, close: () => void) => {
    setSleep(mode);
    close();
    if (mode.kind === "timer") toast.info(`Sleep timer set for ${mode.minutes} minutes.`);
    if (mode.kind === "chapter") toast.info("Playback will stop at the end of this chapter.");
  };
  return (
    <Popover
      label="Sleep timer"
      trigger={(open, toggle) => (
        <ToolButton label={countdown ? `Sleep timer: ${countdown}` : "Sleep timer"} active={open || sleep.kind !== "off"} onClick={toggle}>
          <Moon className="size-4" />
          {countdown && <span className="tabular-nums">{sleep.kind === "chapter" ? "Chapter" : countdown}</span>}
        </ToolButton>
      )}
    >
      {(close) => (
        <>
          <p className="px-3 pt-1.5 pb-1 eyebrow">Sleep timer</p>
          {SLEEP_OPTIONS.map((m) => (
            <MenuItem key={m} active={sleep.kind === "timer" && sleep.minutes === m} onClick={() => choose({ kind: "timer", minutes: m, endsAt: Date.now() + m * 60_000 }, close)}>
              {m} minutes
            </MenuItem>
          ))}
          <MenuItem active={sleep.kind === "chapter"} onClick={() => choose({ kind: "chapter" }, close)}>
            End of chapter
          </MenuItem>
          {sleep.kind !== "off" && (
            <MenuItem onClick={() => choose({ kind: "off" }, close)}>
              <span className="text-rose-400">Turn off</span>
            </MenuItem>
          )}
        </>
      )}
    </Popover>
  );
}

export function VolumeControl() {
  const { volume, muted, setVolume, toggleMute } = usePlayer();
  const Icon = muted || volume === 0 ? VolumeX : volume < 0.5 ? Volume1 : Volume2;
  return (
    <div className="flex items-center gap-1">
      <IconButton label={muted ? "Unmute" : "Mute"} size="md" onClick={toggleMute}>
        <Icon className="size-4" />
      </IconButton>
      <input
        type="range"
        className="range w-20 max-sm:hidden"
        min={0}
        max={1}
        step={0.05}
        value={muted ? 0 : volume}
        onChange={(e) => setVolume(Number(e.target.value))}
        aria-label="Volume"
      />
    </div>
  );
}

export function BookmarkControl() {
  const { bookId, playback, trackIndex } = usePlayer();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [at, setAt] = useState(0);
  const qc = useQueryClient();
  const track = playback?.tracks[trackIndex];
  const add = useMutation({
    mutationFn: () => playerApi.addBookmark(bookId!, { chapter_id: track?.chapter_id ?? null, position_seconds: at, note: note.trim() || null }),
    onSuccess: async (bm) => {
      setOpen(false);
      setNote("");
      toast.success(`Bookmarked ${bm.chapter_title ?? ""} at ${formatClock(bm.position_seconds)}.`);
      await usePlayer.getState().refreshPlayback();
      void qc.invalidateQueries({ queryKey: qk.playback(bookId!) });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (!bookId || !track) return null;
  return (
    <>
      <ToolButton
        label="Add bookmark"
        onClick={() => {
          setAt(usePlayer.getState().position);
          setOpen(true);
        }}
      >
        <Bookmark className="size-4" />
      </ToolButton>
      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="Add bookmark"
        description={`${track.title} · ${formatClock(at)}`}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary" loading={add.isPending} onClick={() => add.mutate()}>
              Save bookmark
            </Button>
          </>
        }
      >
        <label htmlFor="bm-note" className="mb-1.5 block text-[13px] text-paper-300">
          Note (optional)
        </label>
        <Textarea id="bm-note" rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Important conversation…" maxLength={2000} />
      </Dialog>
    </>
  );
}
