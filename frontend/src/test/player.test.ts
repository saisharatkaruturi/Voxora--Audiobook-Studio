import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Playback } from "@/types/api";

vi.mock("@/services/api", () => ({
  playerApi: { playback: vi.fn(), saveProgress: vi.fn(() => Promise.resolve({})) },
  systemApi: { preferences: vi.fn(() => Promise.resolve({ playback_rate: 1 })) },
}));

// jsdom has no media playback: a minimal controllable <audio>.
class FakeAudio extends EventTarget {
  src = "";
  currentTime = 0;
  duration = NaN;
  paused = true;
  playbackRate = 1;
  volume = 1;
  preload = "";
  load() {
    queueMicrotask(() => this.dispatchEvent(new Event("loadedmetadata")));
  }
  play() {
    this.paused = false;
    this.dispatchEvent(new Event("play"));
    return Promise.resolve();
  }
  pause() {
    this.paused = true;
    this.dispatchEvent(new Event("pause"));
  }
  removeAttribute() {
    this.src = "";
  }
}
vi.stubGlobal("Audio", FakeAudio);

const playback = (progress: Playback["progress"] = null): Playback => ({
  book: { id: "b1", title: "Book", author: "A", narrator: null, cover_url: null, language: "en" },
  tracks: [
    { chapter_id: "c1", position: 0, title: "One", kind: "chapter", url: "/media/1.mp3?sig=a", duration: 100, offset: 0, timing_source: "provider" },
    { chapter_id: "c2", position: 1, title: "Two", kind: "chapter", url: "/media/2.mp3?sig=b", duration: 200, offset: 100, timing_source: "provider" },
  ],
  total_duration: 300,
  progress,
  bookmarks: [],
});

const flush = () => new Promise((r) => setTimeout(r, 0));

describe("player engine", () => {
  beforeEach(async () => {
    localStorage.clear();
    const { usePlayer } = await import("@/stores/player");
    usePlayer.getState().close();
  });

  it("resumes exactly where the server says the listener stopped", async () => {
    const { usePlayer } = await import("@/stores/player");
    await usePlayer.getState().load("b1", {
      playback: playback({ chapter_id: "c2", chapter_position: 1, position_seconds: 42, book_position_seconds: 142, playback_rate: 1.5, completed: false, updated_at: new Date().toISOString() }),
    });
    await flush();
    const s = usePlayer.getState();
    expect(s.trackIndex).toBe(1);
    expect(s.position).toBe(42);
    expect(s.rate).toBe(1.5);
  });

  it("prefers a newer local position when the last save didn't reach the server", async () => {
    const { usePlayer } = await import("@/stores/player");
    localStorage.setItem("abs.progress.b1", JSON.stringify({ chapterId: "c1", position: 77, rate: 1.25, at: Date.now() }));
    await usePlayer.getState().load("b1", {
      playback: playback({ chapter_id: "c2", chapter_position: 1, position_seconds: 5, book_position_seconds: 105, playback_rate: 1, completed: false, updated_at: new Date(Date.now() - 60_000).toISOString() }),
    });
    expect(usePlayer.getState().trackIndex).toBe(0);
    expect(usePlayer.getState().position).toBe(77);
  });

  it("skips backwards across a chapter boundary", async () => {
    const { usePlayer } = await import("@/stores/player");
    await usePlayer.getState().load("b1", { chapterId: "c2", position: 5, playback: playback() });
    await flush();
    usePlayer.getState().skip(-15);
    expect(usePlayer.getState().trackIndex).toBe(0);
    expect(usePlayer.getState().position).toBe(90); // 100 + (5 - 15)
  });

  it("seeks across the whole book", async () => {
    const { usePlayer, bookPosition } = await import("@/stores/player");
    await usePlayer.getState().load("b1", { playback: playback() });
    await flush();
    usePlayer.getState().seekBook(150);
    expect(usePlayer.getState().trackIndex).toBe(1);
    expect(bookPosition(usePlayer.getState())).toBeCloseTo(150);
  });

  it("clamps playback speed", async () => {
    const { usePlayer } = await import("@/stores/player");
    usePlayer.getState().setRate(9);
    expect(usePlayer.getState().rate).toBe(3);
    usePlayer.getState().setRate(0.1);
    expect(usePlayer.getState().rate).toBe(0.5);
  });
});
