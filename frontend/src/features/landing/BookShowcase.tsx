import { useMemo, useState } from "react";
import { Pause, Play } from "lucide-react";
import { OpenBook } from "@/components/book3d/OpenBook";
import { BOOK_AUTHOR, BOOK_TITLE, RIFFLE, buildSpread, type SpreadKey } from "@/features/landing/bookPages";
import { VOICES, useDemoNarration, type DemoNarration } from "@/features/landing/useDemoNarration";
import { cn } from "@/utils/format";

/**
 * The landing page's hero object: the glowing 3D book, leafing through "The
 * Starlight Archive" until someone listens, plus a glass player bar that plays
 * the opening in a real voice with every sentence lit as it is spoken.
 */

function fmt(t: number) {
  const s = Math.max(0, Math.round(t));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function PlayerBar({ demo }: { demo: DemoNarration }) {
  const pct = demo.duration ? Math.min(100, (demo.time / demo.duration) * 100) : 0;
  return (
    <div className="glass flex w-full max-w-[520px] items-center gap-3 rounded-full py-2 pr-3 pl-2">
      <button
        type="button"
        onClick={demo.toggle}
        disabled={!demo.ready}
        aria-label={demo.playing ? "Pause the sample" : "Play the sample"}
        className="grid size-11 shrink-0 place-items-center rounded-full bg-orchid-500 text-[var(--on-accent)] transition-transform duration-200 hover:scale-105 active:scale-95"
      >
        {demo.playing ? <Pause className="size-5" fill="currentColor" /> : <Play className="ml-0.5 size-5" fill="currentColor" />}
      </button>
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <div className="flex items-center justify-between gap-2 text-[13px]">
          <span className="truncate font-medium text-paper-50">{demo.playing || demo.time > 0 ? BOOK_TITLE : "Hear the opening"}</span>
          <span className="shrink-0 text-paper-300 tabular-nums">
            {fmt(demo.time)} / {fmt(demo.duration)}
          </span>
        </div>
        <div className="h-1 overflow-hidden rounded-full bg-paper-100/15">
          <div className="h-full rounded-full bg-orchid-500 transition-[width] duration-150" style={{ width: `${pct}%` }} />
        </div>
      </div>
      <div role="radiogroup" aria-label="Narrator" className="hidden shrink-0 gap-0.5 rounded-full bg-white/[0.06] p-0.5 sm:flex">
        {VOICES.map((v) => (
          <button
            key={v.key}
            type="button"
            role="radio"
            aria-checked={demo.voice === v.key}
            title={`${v.name} · ${v.accent}`}
            onClick={() => demo.setVoice(v.key)}
            className={cn(
              "rounded-full px-2.5 py-1 text-[12px] font-medium transition-colors",
              demo.voice === v.key ? "bg-orchid-500 text-[var(--on-accent)]" : "text-paper-300 hover:text-paper-50",
            )}
          >
            {v.name}
          </button>
        ))}
      </div>
    </div>
  );
}

export function BookShowcase({ className }: { className?: string }) {
  const demo = useDemoNarration();
  const [spreadKey] = useState<SpreadKey>("reading");
  const spread = useMemo(
    () => buildSpread(spreadKey, { sentences: demo.sentences, active: demo.active, cleanup: false, onSeek: demo.seekSentence }),
    [spreadKey, demo.sentences, demo.active, demo.seekSentence],
  );
  // Until someone listens, the book leafs through the story, glowing.
  const idle = !demo.playing && demo.time === 0;
  return (
    <div className={cn("flex flex-col items-center justify-center gap-5", className)}>
      <OpenBook
        spread={spread}
        riffle={idle ? RIFFLE : null}
        glow={idle ? 1 : demo.playing ? 0.55 : 0.75}
        title={BOOK_TITLE}
        author={BOOK_AUTHOR}
        className="min-h-0 w-full flex-1"
      />
      <PlayerBar demo={demo} />
    </div>
  );
}
