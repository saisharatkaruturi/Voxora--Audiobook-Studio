import { useEffect, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { Notice, PageLoader } from "@/components/ui/Feedback";
import { chaptersApi } from "@/services/api";
import { errorMessage } from "@/services/http";
import { usePlayer } from "@/stores/player";
import type { SentenceTiming } from "@/types/api";
import { cn } from "@/utils/format";

interface Piece {
  text: string;
  timing: SentenceTiming | null;
  index: number; // sentence index, -1 for untimed text
}

/**
 * Synchronized reading: the sentence being narrated is highlighted and kept in view.
 * Timings come from the TTS engine when it reports them, otherwise they are
 * approximated from text length and audio duration (labelled as such).
 */
export function ReadAlong({ chapterId }: { chapterId: string }) {
  const timings = useQuery({ queryKey: ["timings", chapterId], queryFn: () => chaptersApi.timings(chapterId), staleTime: Infinity });
  const position = usePlayer((s) => s.position);
  const seek = usePlayer((s) => s.seek);
  const container = useRef<HTMLDivElement>(null);
  const lastUserScroll = useRef(0);

  const paragraphs = useMemo(() => {
    if (!timings.data) return [];
    const byPara = new Map<number, SentenceTiming[]>();
    timings.data.sentences.forEach((s) => {
      const list = byPara.get(s[0]) ?? [];
      list.push(s);
      byPara.set(s[0], list);
    });
    let counter = 0;
    const indexOf = new Map<SentenceTiming, number>();
    timings.data.sentences.forEach((s) => indexOf.set(s, counter++));
    return timings.data.paragraphs.map((p) => {
      const sentences = (byPara.get(p.position) ?? []).slice().sort((a, b) => a[1] - b[1]);
      const pieces: Piece[] = [];
      let cursor = 0;
      for (const s of sentences) {
        if (s[1] > cursor) pieces.push({ text: p.text.slice(cursor, s[1]), timing: null, index: -1 });
        pieces.push({ text: p.text.slice(s[1], s[2]), timing: s, index: indexOf.get(s)! });
        cursor = Math.max(cursor, s[2]);
      }
      if (cursor < p.text.length) pieces.push({ text: p.text.slice(cursor), timing: null, index: -1 });
      return { ...p, pieces };
    });
  }, [timings.data]);

  const active = useMemo(() => {
    const list = timings.data?.sentences ?? [];
    // Binary search over start times.
    let lo = 0;
    let hi = list.length - 1;
    let found = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (list[mid][3] <= position + 0.05) {
        found = mid;
        lo = mid + 1;
      } else hi = mid - 1;
    }
    return found;
  }, [timings.data, position]);

  useEffect(() => {
    if (active < 0 || Date.now() - lastUserScroll.current < 4000) return;
    const el = container.current?.querySelector<HTMLElement>(`[data-s="${active}"]`);
    const box = container.current;
    if (!el || !box) return;
    const top = el.offsetTop - box.clientHeight * 0.35;
    box.scrollTo({ top, behavior: "smooth" });
  }, [active]);

  if (timings.isPending) return <PageLoader label="Loading text" />;
  if (timings.isError) return <Notice kind="error">{errorMessage(timings.error)}</Notice>;
  if (!timings.data.sentences.length) return <Notice kind="info">Read-along isn't available for this chapter.</Notice>;

  return (
    <div className="flex h-full min-h-0 flex-col">
      {timings.data.timing_source && timings.data.timing_source !== "provider" && (
        <p className="mb-3 text-[11px] text-paper-500">Highlighting is approximated from the audio length; it may drift slightly.</p>
      )}
      <div
        ref={container}
        onWheel={() => (lastUserScroll.current = Date.now())}
        onTouchMove={() => (lastUserScroll.current = Date.now())}
        className="relative min-h-0 flex-1 space-y-5 overflow-y-auto pr-2 [mask-image:linear-gradient(transparent,black_6%,black_90%,transparent)]"
      >
        <div className="h-4" />
        {paragraphs.map((p) =>
          p.kind === "heading" ? (
            <h3 key={p.position} className="font-serif text-2xl text-paper-50">
              {p.pieces.map((piece, i) => (
                <Sentence key={i} piece={piece} active={piece.index === active} past={piece.index >= 0 && piece.index < active} onSeek={seek} />
              ))}
            </h3>
          ) : (
            <p key={p.position} className="reading">
              {p.pieces.map((piece, i) => (
                <Sentence key={i} piece={piece} active={piece.index === active} past={piece.index >= 0 && piece.index < active} onSeek={seek} />
              ))}
            </p>
          ),
        )}
        <div className="h-[30vh]" />
      </div>
    </div>
  );
}

function Sentence({ piece, active, past, onSeek }: { piece: Piece; active: boolean; past: boolean; onSeek: (t: number) => void }) {
  if (!piece.timing) return <span className="text-paper-200">{piece.text}</span>;
  return (
    <span
      data-s={piece.index}
      role="button"
      tabIndex={-1}
      onClick={() => onSeek(piece.timing![3])}
      className={cn(
        "cursor-pointer rounded-md transition-colors duration-300",
        active
          ? "bg-mint-400/15 text-paper-50 [box-decoration-break:clone] shadow-[0_0_0_3px_rgb(95_255_210/0.22)]"
          : past
            ? "text-paper-400 hover:text-paper-200"
            : "text-paper-200 hover:text-paper-50",
      )}
      aria-current={active ? "true" : undefined}
    >
      {piece.text}
    </span>
  );
}
