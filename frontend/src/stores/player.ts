/**
 * Audiobook player engine.
 *
 * One HTMLAudioElement lives outside React for the whole session, so playback
 * continues while the user navigates. The store mirrors its state for the UI.
 * Progress is saved to the server every few seconds while playing, on pause,
 * on chapter change and when the page is hidden (keepalive request), and a
 * local copy is kept so a lost connection never loses the listener's place.
 */
import { create } from "zustand";
import { playerApi, systemApi } from "@/services/api";
import { getChapter, pullTrack, syncBook, trackKey } from "@/services/deviceAudio";
import { queryClient, qk } from "@/services/queryClient";
import type { Playback, Track } from "@/types/api";

export type SleepMode = { kind: "off" } | { kind: "timer"; endsAt: number; minutes: number } | { kind: "chapter" };

export const SPEEDS = [0.75, 1, 1.1, 1.25, 1.5, 1.75, 2] as const;

interface PlayerState {
  bookId: string | null;
  playback: Playback | null;
  trackIndex: number;
  position: number; // seconds within the current track
  duration: number; // current track duration
  playing: boolean;
  buffering: boolean;
  rate: number;
  volume: number;
  muted: boolean;
  sleep: SleepMode;
  error: string | null;
  fullscreen: boolean;

  load: (bookId: string, opts?: { chapterId?: string | null; position?: number; autoplay?: boolean; playback?: Playback }) => Promise<void>;
  play: () => Promise<void>;
  pause: () => void;
  toggle: () => void;
  seek: (seconds: number) => void;
  seekBook: (seconds: number) => void;
  skip: (delta: number) => void;
  selectTrack: (index: number, position?: number, autoplay?: boolean) => void;
  next: () => void;
  previous: () => void;
  setRate: (rate: number) => void;
  setVolume: (volume: number) => void;
  toggleMute: () => void;
  setSleep: (mode: SleepMode) => void;
  setFullscreen: (v: boolean) => void;
  refreshPlayback: () => Promise<void>;
  close: () => void;
}

let audio: HTMLAudioElement | null = null;
let lastSaved = 0;
let recovering = false;
// Which chapter audio is loaded (chapter + content hash), and the blob: URL serving it.
let currentKey: string | null = null;
let objectUrl: string | null = null;
let loadToken = 0;

const ELSEWHERE =
  "This chapter's audio is saved on the device where the book was converted. Re-create the audio from the book page to listen here.";

/**
 * Prefer the copy on this device. In device mode, a chapter still on the server is
 * fetched onto the device first: streaming the server copy would break when the
 * hand-off deletes it mid-play.
 */
async function resolveSource(track: Track): Promise<string | null> {
  const local = await getChapter(track.chapter_id, trackKey(track));
  if (local) return URL.createObjectURL(local.blob);
  const s = usePlayer.getState();
  if (track.url && s.bookId && s.playback?.audio_delivery === "device") {
    try {
      if (await pullTrack(s.bookId, track)) {
        const pulled = await getChapter(track.chapter_id, trackKey(track));
        if (pulled) return URL.createObjectURL(pulled.blob);
      }
    } catch {
      /* fall back to streaming */
    }
  }
  return track.url;
}
const SAVE_INTERVAL_MS = 8000;

const LOCAL_KEY = (bookId: string) => `abs.progress.${bookId}`;

function localSave(bookId: string, data: { chapterId: string; position: number; rate: number; at: number }) {
  try {
    localStorage.setItem(LOCAL_KEY(bookId), JSON.stringify(data));
  } catch {
    /* ignore */
  }
}

export function localProgress(bookId: string): { chapterId: string; position: number; rate: number; at: number } | null {
  try {
    const raw = localStorage.getItem(LOCAL_KEY(bookId));
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

// --- Audio level (drives the 3D book and waveforms) ------------------------------
let analyser: AnalyserNode | null = null;
let audioCtx: AudioContext | null = null;
let levelBuf: Uint8Array<ArrayBuffer> | null = null;

/** Attach an analyser once, only for same-origin media (cross-origin audio would be muted by CORS). */
function ensureAnalyser(a: HTMLAudioElement) {
  if (analyser || typeof AudioContext === "undefined") return;
  try {
    if (new URL(a.src, window.location.href).origin !== window.location.origin) return;
    audioCtx = new AudioContext();
    const src = audioCtx.createMediaElementSource(a);
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 512;
    analyser.smoothingTimeConstant = 0.8;
    src.connect(analyser);
    analyser.connect(audioCtx.destination);
    levelBuf = new Uint8Array(analyser.fftSize);
  } catch {
    analyser = null;
  }
}

/** Current playback loudness 0..1 (RMS of the waveform); 0 when paused or unavailable. */
export function audioLevel(): number {
  if (!analyser || !levelBuf || !audio || audio.paused) return 0;
  analyser.getByteTimeDomainData(levelBuf);
  let sum = 0;
  for (let i = 0; i < levelBuf.length; i++) {
    const v = (levelBuf[i] - 128) / 128;
    sum += v * v;
  }
  return Math.min(1, Math.sqrt(sum / levelBuf.length) * 3.2);
}

function getAudio(): HTMLAudioElement {
  if (audio) return audio;
  audio = new Audio();
  audio.preload = "auto";
  const a = audio;
  const set = usePlayer.setState;
  const get = usePlayer.getState;
  a.addEventListener("timeupdate", () => {
    set({ position: a.currentTime });
    if (!a.paused && Date.now() - lastSaved > SAVE_INTERVAL_MS) saveProgress();
  });
  a.addEventListener("durationchange", () => set({ duration: Number.isFinite(a.duration) ? a.duration : get().duration }));
  a.addEventListener("play", () => set({ playing: true, error: null }));
  a.addEventListener("pause", () => {
    set({ playing: false });
    saveProgress();
  });
  a.addEventListener("waiting", () => set({ buffering: true }));
  a.addEventListener("playing", () => set({ buffering: false }));
  a.addEventListener("canplay", () => set({ buffering: false }));
  a.addEventListener("ended", () => {
    const s = get();
    const last = !s.playback || s.trackIndex >= s.playback.tracks.length - 1;
    if (s.sleep.kind === "chapter") {
      set({ sleep: { kind: "off" }, playing: false });
      if (!last) s.selectTrack(s.trackIndex + 1, 0, false);
      return;
    }
    if (last) {
      set({ playing: false });
      saveProgress({ completed: true });
      return;
    }
    s.selectTrack(s.trackIndex + 1, 0, true);
  });
  a.addEventListener("error", () => {
    const s = get();
    if (!s.bookId || !a.src) return;
    // Signed media URLs expire; fetch fresh ones once and continue where we were.
    if (!recovering) {
      recovering = true;
      const at = a.currentTime;
      const wasPlaying = s.playing;
      currentKey = null; // force a fresh source: the chapter may now be on this device
      s.refreshPlayback()
        .then(() => get().selectTrack(get().trackIndex, at, wasPlaying))
        .catch(() => set({ error: "The audio couldn't be loaded right now. It will work again once VOXORA is reachable; press play to retry.", playing: false }))
        .finally(() => setTimeout(() => (recovering = false), 5000));
      return;
    }
    set({ error: "This chapter's audio couldn't be played. It may have been deleted or regenerated.", playing: false, buffering: false });
  });

  if (typeof document !== "undefined") {
    const flush = () => saveProgress({ keepalive: true });
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") flush();
    });
    window.addEventListener("pagehide", flush);
  }
  setupSleepTicker();
  return a;
}

async function defaultRate(): Promise<number | null> {
  try {
    return (await queryClient.fetchQuery({ queryKey: qk.prefs, queryFn: systemApi.preferences, staleTime: 60_000 })).playback_rate;
  } catch {
    return null;
  }
}

function currentTrack(s = usePlayer.getState()): Track | null {
  return s.playback?.tracks[s.trackIndex] ?? null;
}

export function saveProgress(opts: { completed?: boolean; keepalive?: boolean } = {}) {
  const s = usePlayer.getState();
  const track = currentTrack(s);
  if (!s.bookId || !track || !audio) return;
  lastSaved = Date.now();
  const position = Math.max(0, audio.currentTime || s.position);
  localSave(s.bookId, { chapterId: track.chapter_id, position, rate: s.rate, at: Date.now() });
  playerApi
    .saveProgress(s.bookId, { chapter_id: track.chapter_id, position_seconds: position, playback_rate: s.rate, completed: !!opts.completed }, opts.keepalive)
    .catch(() => {
      /* kept locally; retried on the next save */
    });
}

function setupSleepTicker() {
  setInterval(() => {
    const s = usePlayer.getState();
    if (s.sleep.kind !== "timer" || !audio) return;
    const left = s.sleep.endsAt - Date.now();
    if (left <= 0) {
      audio.pause();
      audio.volume = s.muted ? 0 : s.volume;
      usePlayer.setState({ sleep: { kind: "off" } });
      return;
    }
    // Gentle fade over the final 12 seconds.
    if (left < 12_000 && !audio.paused) audio.volume = Math.max(0, (s.muted ? 0 : s.volume) * (left / 12_000));
  }, 500);
}

function updateMediaSession() {
  if (typeof navigator === "undefined" || !("mediaSession" in navigator)) return;
  const s = usePlayer.getState();
  const track = currentTrack(s);
  if (!s.playback || !track) return;
  try {
    navigator.mediaSession.metadata = new MediaMetadata({
      title: track.title,
      artist: s.playback.book.author ?? "",
      album: s.playback.book.title,
      artwork: s.playback.book.cover_url ? [{ src: s.playback.book.cover_url, sizes: "600x900", type: "image/jpeg" }] : [],
    });
    navigator.mediaSession.setActionHandler("play", () => void usePlayer.getState().play());
    navigator.mediaSession.setActionHandler("pause", () => usePlayer.getState().pause());
    navigator.mediaSession.setActionHandler("seekbackward", () => usePlayer.getState().skip(-15));
    navigator.mediaSession.setActionHandler("seekforward", () => usePlayer.getState().skip(30));
    navigator.mediaSession.setActionHandler("previoustrack", () => usePlayer.getState().previous());
    navigator.mediaSession.setActionHandler("nexttrack", () => usePlayer.getState().next());
  } catch {
    /* unsupported action */
  }
}

export const usePlayer = create<PlayerState>((set, get) => ({
  bookId: null,
  playback: null,
  trackIndex: 0,
  position: 0,
  duration: 0,
  playing: false,
  buffering: false,
  rate: 1,
  volume: 1,
  muted: false,
  sleep: { kind: "off" },
  error: null,
  fullscreen: false,

  async load(bookId, opts = {}) {
    const a = getAudio();
    if (get().bookId && get().bookId !== bookId) saveProgress();
    const playback = opts.playback ?? (await playerApi.playback(bookId));
    // Device delivery: pull any finished chapters onto this device in the background.
    if (playback.audio_delivery === "device") void syncBook(bookId, playback).catch(() => undefined);
    if (!playback.tracks.length) {
      set({ bookId, playback, error: "This book has no generated audio yet." });
      return;
    }
    // Choose a resume point: explicit > server progress > local copy (if newer).
    let chapterId = opts.chapterId ?? playback.progress?.chapter_id ?? null;
    let position = opts.position ?? playback.progress?.position_seconds ?? 0;
    let rate = playback.progress?.playback_rate ?? (await defaultRate()) ?? get().rate;
    const local = localProgress(bookId);
    const serverAt = playback.progress ? new Date(playback.progress.updated_at).getTime() : 0;
    if (opts.chapterId === undefined && local && local.at > serverAt + 2000) {
      chapterId = local.chapterId;
      position = local.position;
      rate = local.rate;
    }
    if (playback.progress?.completed && opts.chapterId === undefined) {
      chapterId = null;
      position = 0;
    }
    let index = Math.max(0, playback.tracks.findIndex((t) => t.chapter_id === chapterId));
    if (chapterId === null) index = 0;
    set({ bookId, playback, rate, error: null, sleep: get().bookId === bookId ? get().sleep : { kind: "off" } });
    a.playbackRate = rate;
    get().selectTrack(index, position, !!opts.autoplay);
  },

  async play() {
    const a = getAudio();
    if (!a.src) return;
    a.volume = get().muted ? 0 : get().volume;
    ensureAnalyser(a);
    if (audioCtx?.state === "suspended") await audioCtx.resume().catch(() => undefined);
    try {
      await a.play();
    } catch (err) {
      if ((err as Error).name !== "AbortError") set({ error: "Playback was blocked by the browser. Press play again.", playing: false });
    }
  },

  pause() {
    audio?.pause();
  },

  toggle() {
    if (!audio) return;
    if (audio.paused) void get().play();
    else get().pause();
  },

  seek(seconds) {
    const a = getAudio();
    const d = get().duration || a.duration || 0;
    const t = Math.max(0, Math.min(d ? d - 0.25 : seconds, seconds));
    a.currentTime = t;
    set({ position: t });
    lastSaved = 0;
  },

  seekBook(seconds) {
    const pb = get().playback;
    if (!pb) return;
    const idx = pb.tracks.findIndex((t, i) => seconds < t.offset + t.duration || i === pb.tracks.length - 1);
    const track = pb.tracks[idx];
    if (idx === get().trackIndex) get().seek(seconds - track.offset);
    else get().selectTrack(idx, seconds - track.offset, get().playing);
  },

  skip(delta) {
    const s = get();
    const pb = s.playback;
    const a = getAudio();
    if (!pb) return;
    const target = a.currentTime + delta;
    if (target < 0 && s.trackIndex > 0) {
      const prev = pb.tracks[s.trackIndex - 1];
      s.selectTrack(s.trackIndex - 1, Math.max(0, prev.duration + target), s.playing);
    } else if (target > (s.duration || Infinity) && s.trackIndex < pb.tracks.length - 1) {
      s.selectTrack(s.trackIndex + 1, target - s.duration, s.playing);
    } else {
      s.seek(target);
    }
  },

  selectTrack(index, position = 0, autoplay = false) {
    const pb = get().playback;
    const a = getAudio();
    if (!pb || !pb.tracks[index]) return;
    const track = pb.tracks[index];
    const key = `${track.chapter_id}:${track.audio_hash ?? track.url ?? ""}`;
    const changed = key !== currentKey || !a.src;
    set({ trackIndex: index, position, duration: track.duration, buffering: changed, error: null });
    const start = () => {
      a.currentTime = Math.min(position, Math.max(0, track.duration - 0.5));
      a.playbackRate = get().rate;
      if (autoplay) void get().play();
    };
    if (changed) {
      currentKey = key;
      const token = ++loadToken;
      void resolveSource(track).then((src) => {
        if (token !== loadToken) {
          if (src?.startsWith("blob:")) URL.revokeObjectURL(src);
          return;
        }
        if (!src) {
          currentKey = null;
          set({ error: ELSEWHERE, buffering: false, playing: false });
          return;
        }
        if (objectUrl) URL.revokeObjectURL(objectUrl);
        objectUrl = src.startsWith("blob:") ? src : null;
        a.src = src;
        a.addEventListener("loadedmetadata", start, { once: true });
        a.load();
      });
    } else start();
    updateMediaSession();
    lastSaved = 0;
    setTimeout(() => saveProgress(), 300);
  },

  next() {
    const s = get();
    if (s.playback && s.trackIndex < s.playback.tracks.length - 1) s.selectTrack(s.trackIndex + 1, 0, s.playing);
  },

  previous() {
    const s = get();
    // Like most players: restart the chapter unless we're at its very beginning.
    if ((audio?.currentTime ?? 0) > 4 || s.trackIndex === 0) s.seek(0);
    else s.selectTrack(s.trackIndex - 1, 0, s.playing);
  },

  setRate(rate) {
    const r = Math.min(3, Math.max(0.5, rate));
    if (audio) audio.playbackRate = r;
    set({ rate: r });
    lastSaved = 0;
  },

  setVolume(volume) {
    const v = Math.min(1, Math.max(0, volume));
    if (audio) audio.volume = v;
    set({ volume: v, muted: v === 0 });
  },

  toggleMute() {
    const muted = !get().muted;
    if (audio) audio.volume = muted ? 0 : get().volume || 1;
    set({ muted, volume: !muted && get().volume === 0 ? 1 : get().volume });
  },

  setSleep(mode) {
    if (audio) audio.volume = get().muted ? 0 : get().volume;
    set({ sleep: mode });
  },

  setFullscreen(v) {
    set({ fullscreen: v });
  },

  async refreshPlayback() {
    const id = get().bookId;
    if (!id) return;
    const playback = await playerApi.playback(id);
    set({ playback });
  },

  close() {
    saveProgress();
    if (audio) {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    }
    currentKey = null;
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = null;
    set({ bookId: null, playback: null, playing: false, position: 0, duration: 0, trackIndex: 0, sleep: { kind: "off" }, fullscreen: false });
  },
}));

/** Position across the whole book, in seconds. */
export function bookPosition(s: Pick<PlayerState, "playback" | "trackIndex" | "position">): number {
  const t = s.playback?.tracks[s.trackIndex];
  return t ? t.offset + s.position : 0;
}
