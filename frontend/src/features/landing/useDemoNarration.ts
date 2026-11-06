import { useCallback, useEffect, useRef, useState } from "react";
import { setSkyLevel as setWaveLevel } from "@/components/layout/GalaxySky";

/**
 * The landing page's live sample: the opening of "The Starlight Archive"
 * (an original story, CC0), narrated by three real voices, with sentence timings from the voice
 * service. The sentence being spoken is lit on the book's page, and the voice's
 * loudness drives the moving background.
 */

export type VoiceKey = "aria" | "ryan" | "neerja";

export const VOICES: { key: VoiceKey; name: string; accent: string }[] = [
  { key: "aria", name: "Aria", accent: "American English" },
  { key: "ryan", name: "Ryan", accent: "British English" },
  { key: "neerja", name: "Neerja", accent: "Indian English" },
];

interface Timed {
  text: string;
  t0: number;
  t1: number;
}

interface DemoData {
  passage: string[];
  voices: Record<VoiceKey, Timed[]>;
}

export function useDemoNarration() {
  const [data, setData] = useState<DemoData | null>(null);
  const [voice, setVoiceState] = useState<VoiceKey>("aria");
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [rate, setRateState] = useState(1);
  const [active, setActive] = useState(-1);
  const audio = useRef<HTMLAudioElement | null>(null);
  const analyser = useRef<{ ctx: AudioContext; node: AnalyserNode; buf: Uint8Array<ArrayBuffer> } | null>(null);
  const raf = useRef(0);
  const voiceRef = useRef<VoiceKey>("aria");
  const dataRef = useRef<DemoData | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/demo/story.json")
      .then((r) => r.json())
      .then((d: DemoData) => {
        if (cancelled) return;
        setData(d);
        dataRef.current = d;
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const ensureAudio = useCallback(() => {
    if (audio.current) return audio.current;
    const a = new Audio(`/demo/${voiceRef.current}.mp3`);
    a.preload = "auto";
    a.addEventListener("loadedmetadata", () => setDuration(a.duration || 0));
    a.addEventListener("ended", () => {
      setPlaying(false);
      setWaveLevel(0);
    });
    a.addEventListener("pause", () => setPlaying(false));
    a.addEventListener("play", () => setPlaying(true));
    audio.current = a;
    return a;
  }, []);

  // Route the audio through an analyser only once the audio engine is really running:
  // a suspended context (autoplay rules, no output device) would otherwise stall playback.
  const attachAnalyser = async (a: HTMLAudioElement) => {
    if (analyser.current || typeof AudioContext === "undefined") return;
    try {
      const ctx = new AudioContext();
      if (ctx.state !== "running") await Promise.race([ctx.resume(), new Promise((r) => setTimeout(r, 300))]);
      if (ctx.state !== "running") {
        void ctx.close();
        return;
      }
      const src = ctx.createMediaElementSource(a);
      const node = ctx.createAnalyser();
      node.fftSize = 512;
      src.connect(node);
      node.connect(ctx.destination);
      analyser.current = { ctx, node, buf: new Uint8Array(node.fftSize) };
    } catch {
      analyser.current = null;
    }
  };

  const tick = useCallback(() => {
    const a = audio.current;
    const d = dataRef.current;
    if (!a || !d) return;
    const t = a.currentTime;
    setTime(t);
    const sents = d.voices[voiceRef.current];
    let idx = -1;
    for (let i = 0; i < sents.length; i++) if (t >= sents[i].t0 - 0.05) idx = i;
    setActive(idx);
    const an = analyser.current;
    if (!an && !a.paused) {
      // No analyser: let the waves follow the rhythm of the sentences instead.
      const s = idx >= 0 ? sents[idx] : null;
      setWaveLevel(s && t < s.t1 ? 0.35 + 0.25 * Math.abs(Math.sin(t * 6)) : 0.1);
    }
    if (an && !a.paused) {
      an.node.getByteTimeDomainData(an.buf);
      let sum = 0;
      for (let i = 0; i < an.buf.length; i++) {
        const v = (an.buf[i] - 128) / 128;
        sum += v * v;
      }
      setWaveLevel(Math.min(1, Math.sqrt(sum / an.buf.length) * 4));
    }
    if (!a.paused) raf.current = requestAnimationFrame(tick);
  }, []);

  const play = useCallback(async () => {
    const a = ensureAudio();
    a.playbackRate = rate;
    await attachAnalyser(a);
    if (a.ended || (a.duration && a.currentTime >= a.duration - 0.05)) a.currentTime = 0;
    await a.play().catch(() => undefined);
    cancelAnimationFrame(raf.current);
    raf.current = requestAnimationFrame(tick);
  }, [ensureAudio, rate, tick]);

  const pause = useCallback(() => {
    audio.current?.pause();
    setWaveLevel(0);
  }, []);

  const toggle = useCallback(() => (playing ? pause() : void play()), [playing, pause, play]);

  /** Jump to a sentence (tap on the page). */
  const seekSentence = useCallback(
    (i: number) => {
      const d = dataRef.current;
      if (!d) return;
      const a = ensureAudio();
      const s = d.voices[voiceRef.current][i];
      if (!s) return;
      a.currentTime = s.t0;
      setActive(i);
      setTime(s.t0);
      if (a.paused) void play();
    },
    [ensureAudio, play],
  );

  /** Change narrator, keeping the place: the same sentence in the new voice. */
  const setVoice = useCallback(
    (v: VoiceKey) => {
      if (v === voiceRef.current) return;
      const d = dataRef.current;
      const a = audio.current;
      const wasPlaying = !!a && !a.paused;
      const sentence = Math.max(0, active);
      voiceRef.current = v;
      setVoiceState(v);
      if (!a) return;
      a.pause();
      a.src = `/demo/${v}.mp3`;
      a.addEventListener(
        "loadedmetadata",
        () => {
          a.currentTime = d?.voices[v][sentence]?.t0 ?? 0;
          a.playbackRate = rate;
          if (wasPlaying) void play();
          else tick();
        },
        { once: true },
      );
      a.load();
    },
    [active, play, rate, tick],
  );

  const setRate = useCallback((r: number) => {
    setRateState(r);
    if (audio.current) audio.current.playbackRate = r;
  }, []);

  useEffect(
    () => () => {
      cancelAnimationFrame(raf.current);
      audio.current?.pause();
      setWaveLevel(0);
      void analyser.current?.ctx.close().catch(() => undefined);
    },
    [],
  );

  return {
    ready: !!data,
    sentences: data ? data.voices[voice] : [],
    voice,
    setVoice,
    playing,
    toggle,
    time,
    duration: duration || (data ? (data.voices[voice].at(-1)?.t1 ?? 0) : 0),
    rate,
    setRate,
    active,
    seekSentence,
  };
}

export type DemoNarration = ReturnType<typeof useDemoNarration>;
