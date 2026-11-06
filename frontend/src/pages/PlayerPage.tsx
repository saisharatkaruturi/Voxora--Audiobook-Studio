import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ChevronDown, Keyboard, ListMusic, BookOpenText, Bookmark as BookmarkIcon } from "lucide-react";
import { BookmarkControl, Scrubber, SleepControl, SpeedControl, TransportControls, VolumeControl, useSleepCountdown } from "@/components/player/Controls";
import { ButtonLink } from "@/components/ui/Button";
import { EmptyState, Notice, PageLoader } from "@/components/ui/Feedback";
import { Segmented } from "@/components/ui/Form";
import { Dialog } from "@/components/ui/Dialog";
import { BookTimeline } from "@/features/player/BookTimeline";
import { ReadAlong } from "@/features/player/ReadAlong";
import { BookmarksPanel, ChaptersPanel } from "@/features/player/SidePanels";
import { SHORTCUTS } from "@/features/player/usePlayerShortcuts";
import { errorMessage } from "@/services/http";
import { usePlayer } from "@/stores/player";
import { formatClock } from "@/utils/format";
import { Headphones } from "lucide-react";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { brand } from "@/config/brand";
import { BrandBadge } from "@/components/brand/BrandWordmark";
import { LivingCover } from "@/features/player/LivingCover";
import { AudioWaveform } from "@/components/audio/AudioWaveform";
import { audioLevel } from "@/stores/player";

type Panel = "read" | "chapters" | "bookmarks";

export default function PlayerPage() {
  const { bookId = "" } = useParams();
  const { bookId: loaded, playback, trackIndex, error, load, playing } = usePlayer();
  const [loadError, setLoadError] = useState<unknown>(null);
  const [panel, setPanel] = useState<Panel>("read");
  const [keys, setKeys] = useState(false);
  const sleep = useSleepCountdown();
  useDocumentTitle(playback && loaded === bookId ? `${playback.book.title}` : "Audiobook Player");

  // ?chapter=<id> opens a specific chapter (e.g. "Listen" on a chapter that just finished).
  const [params] = useSearchParams();
  const wanted = params.get("chapter");
  useEffect(() => {
    if (loaded !== bookId) {
      setLoadError(null);
      load(bookId, wanted ? { chapterId: wanted, position: 0 } : undefined).catch(setLoadError);
      return;
    }
    const state = usePlayer.getState();
    if (!wanted || !state.playback) return;
    const idx = state.playback.tracks.findIndex((t) => t.chapter_id === wanted);
    if (idx >= 0 && idx !== state.trackIndex) state.selectTrack(idx, 0, false);
    else if (idx < 0) void state.refreshPlayback().then(() => {
      const fresh = usePlayer.getState();
      const i = fresh.playback?.tracks.findIndex((t) => t.chapter_id === wanted) ?? -1;
      if (i >= 0) fresh.selectTrack(i, 0, false);
    });
  }, [bookId, loaded, load, wanted]);

  if (loadError) {
    return (
      <div className="mx-auto max-w-lg pt-10">
        <Notice kind="error" title="This audiobook couldn't be opened">
          {errorMessage(loadError)}
        </Notice>
      </div>
    );
  }
  if (loaded !== bookId || !playback) return <PageLoader label="Opening your story" />;
  if (!playback.tracks.length) {
    return (
      <EmptyState icon={<Headphones className="size-6" />} title="No audio yet" action={<ButtonLink to={`/books/${bookId}/voice`} variant="primary">Choose a voice & create</ButtonLink>}>
        Generate the audiobook first. You can start listening as soon as the first chapter is ready.
      </EmptyState>
    );
  }
  const track = playback.tracks[trackIndex];

  return (
    <div className="relative -mt-6 md:-mt-10">
      {/* Listening room: the cover's colors bloom softly behind everything, with an aurora glow low on the page. */}
      <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden" aria-hidden>
        {playback.book.cover_url && <img src={playback.book.cover_url} alt="" className="size-full scale-125 object-cover opacity-[0.22] blur-[100px] saturate-150" />}
        <div className="absolute inset-0 [background:var(--player-veil)]" />
        <div className="absolute -bottom-[30%] -left-[10%] size-[70vmax] animate-[vx-glow-a_40s_ease-in-out_infinite] rounded-full bg-[radial-gradient(closest-side,var(--player-aurora-a),transparent)]" />
        <div className="absolute -right-[15%] -bottom-[35%] size-[60vmax] animate-[vx-glow-b_52s_ease-in-out_infinite] rounded-full bg-[radial-gradient(closest-side,var(--player-aurora-b),transparent)]" />
      </div>

      <div className="flex items-center justify-between py-4">
        <Link to={`/books/${bookId}`} className="inline-flex items-center gap-1.5 rounded-lg text-sm text-paper-400 hover:text-paper-100" aria-label="Close player, back to book">
          <ChevronDown className="size-5" /> <span className="max-sm:hidden">Book details</span>
        </Link>
        <BrandBadge label={`${brand.name} · Now playing`} />
        <button type="button" onClick={() => setKeys(true)} className="rounded-lg p-2 text-paper-500 hover:text-paper-100 max-md:invisible" aria-label="Keyboard shortcuts">
          <Keyboard className="size-4" />
        </button>
      </div>

      <div className="grid gap-10 lg:grid-cols-[minmax(0,440px)_1fr] lg:gap-14">
        <section aria-label="Player" className="mx-auto flex w-full max-w-[440px] flex-col">
          <LivingCover url={playback.book.cover_url} title={playback.book.title} author={playback.book.author} />
          <div className="mt-5 text-center">
            <p data-testid="current-chapter" className="truncate text-sm font-medium text-orchid-400/90">{track.title}</p>
            <h1 className="mt-1.5 font-display text-2xl leading-tight text-paper-50 sm:text-3xl">{playback.book.title}</h1>
            <p className="mt-1 text-sm text-paper-400">
              {playback.book.author ?? "Unknown author"}
              {playback.book.narrator ? ` · Narrated by ${playback.book.narrator}` : ""}
            </p>
          </div>
          <div className="panel mt-5 px-4 pt-3 pb-4 sm:px-5">
          <AudioWaveform active={playing} level={audioLevel} bars={56} rest={0.3} className="h-9" label="Narration waveform" />
          <div className="mt-3">
            <Scrubber />
          </div>
          <div className="mt-4">
            <TransportControls />
          </div>
          <div className="mt-4 flex flex-wrap items-center justify-center gap-1">
            <SpeedControl />
            <SleepControl />
            <BookmarkControl />
            <VolumeControl />
          </div>
          {sleep && <p className="mt-2 text-center text-xs text-orchid-300/80">Sleep: {sleep}</p>}
          </div>
          {error && (
            <Notice kind="error" className="mt-4">
              {error}
            </Notice>
          )}
          <div className="mt-5 px-1">
            <BookTimeline />
          </div>
          <p className="mt-3 text-center text-xs text-paper-400">
            Chapter {trackIndex + 1} of {playback.tracks.length} · {formatClock(track.duration)}
          </p>
        </section>

        <section aria-label="Book content" className="panel flex min-h-[420px] flex-col p-4 sm:p-7 lg:h-[calc(100dvh-140px)]">
          <Segmented<Panel>
            label="Panel"
            value={panel}
            onChange={setPanel}
            className="mb-5 self-start"
            options={[
              { value: "read", label: <span className="inline-flex items-center gap-1.5"><BookOpenText className="size-3.5" />Read along</span> },
              { value: "chapters", label: <span className="inline-flex items-center gap-1.5"><ListMusic className="size-3.5" />Chapters</span> },
              { value: "bookmarks", label: <span className="inline-flex items-center gap-1.5"><BookmarkIcon className="size-3.5" />Bookmarks{playback.bookmarks.length ? ` (${playback.bookmarks.length})` : ""}</span> },
            ]}
          />
          <div className="min-h-0 flex-1 overflow-y-auto">
            {panel === "read" && <ReadAlong key={track.chapter_id} chapterId={track.chapter_id} />}
            {panel === "chapters" && <ChaptersPanel />}
            {panel === "bookmarks" && <BookmarksPanel />}
          </div>
        </section>
      </div>

      <Dialog open={keys} onClose={() => setKeys(false)} title="Keyboard shortcuts" size="sm">
        <dl className="space-y-2">
          {SHORTCUTS.map(([k, v]) => (
            <div key={k} className="flex justify-between gap-4 text-sm">
              <dt>
                <kbd className="rounded-md border border-white/[0.1] bg-white/[0.04] px-1.5 py-0.5 font-sans text-xs text-paper-200">{k}</kbd>
              </dt>
              <dd className="text-paper-400">{v}</dd>
            </div>
          ))}
        </dl>
      </Dialog>
    </div>
  );
}
