/**
 * Audiobooks stored on the listener's device (AUDIO_DELIVERY=device).
 *
 * The server converts a book chapter by chapter; each finished chapter is
 * downloaded into this browser's storage (IndexedDB) and then confirmed, after
 * which the server deletes its copy. Playback reads from here, so books play
 * offline and the only limit is the device's free space.
 *
 * Entries are keyed by chapter id + the server's content hash of that audio, so
 * a re-narrated chapter is fetched again instead of playing stale audio.
 */
import { playerApi } from "@/services/api";
import { authConfig } from "@/services/supabase";
import type { Playback, Track } from "@/types/api";

const DB_NAME = "voxora-audio";
const STORE = "chapters";

export interface StoredChapter {
  key: string; // `${chapterId}:${hash}`
  bookId: string;
  chapterId: string;
  hash: string;
  format: string;
  size: number;
  savedAt: number;
  blob: Blob;
}

let dbPromise: Promise<IDBDatabase> | null = null;

function openDb(): Promise<IDBDatabase> {
  dbPromise ??= new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") return reject(new Error("This browser can't store audiobooks."));
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      const store = req.result.createObjectStore(STORE, { keyPath: "key" });
      store.createIndex("bookId", "bookId");
      store.createIndex("chapterId", "chapterId");
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => {
      dbPromise = null;
      reject(req.error ?? new Error("Couldn't open audiobook storage."));
    };
  });
  return dbPromise;
}

function tx<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return openDb().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const t = db.transaction(STORE, mode);
        const req = run(t.objectStore(STORE));
        t.oncomplete = () => resolve(req.result);
        t.onerror = () => reject(t.error ?? req.error);
        t.onabort = () => reject(t.error ?? new Error("Storage transaction aborted."));
      }),
  );
}

const keyOf = (chapterId: string, hash: string) => `${chapterId}:${hash}`;

export async function getChapter(chapterId: string, hash: string | null | undefined): Promise<StoredChapter | undefined> {
  if (!hash) return undefined;
  try {
    return await tx<StoredChapter | undefined>("readonly", (s) => s.get(keyOf(chapterId, hash)));
  } catch {
    return undefined;
  }
}

async function chaptersOf(index: "bookId" | "chapterId", value: string): Promise<StoredChapter[]> {
  return tx<StoredChapter[]>("readonly", (s) => s.index(index).getAll(value));
}

async function putChapter(entry: StoredChapter): Promise<void> {
  // Older audio for the same chapter (it was re-narrated) is replaced, not kept.
  for (const old of await chaptersOf("chapterId", entry.chapterId)) {
    if (old.key !== entry.key) await tx("readwrite", (s) => s.delete(old.key));
  }
  await tx("readwrite", (s) => s.put(entry));
}

/** Remove a book's audio from this device (when the book is deleted). */
export async function deleteBookAudio(bookId: string): Promise<void> {
  try {
    for (const c of await chaptersOf("bookId", bookId)) await tx("readwrite", (s) => s.delete(c.key));
  } catch {
    /* storage unavailable: nothing to remove */
  }
}

export async function bookAudio(bookId: string): Promise<StoredChapter[]> {
  try {
    return await chaptersOf("bookId", bookId);
  } catch {
    return [];
  }
}

/** Ask the browser not to evict our storage under pressure (granted silently on most browsers). */
export async function requestPersistence(): Promise<boolean> {
  try {
    if (navigator.storage?.persisted && (await navigator.storage.persisted())) return true;
    return (await navigator.storage?.persist?.()) ?? false;
  } catch {
    return false;
  }
}

export async function storageEstimate(): Promise<{ used: number; quota: number } | null> {
  try {
    const e = await navigator.storage?.estimate?.();
    return e ? { used: e.usage ?? 0, quota: e.quota ?? 0 } : null;
  } catch {
    return null;
  }
}

export async function deviceDelivery(): Promise<boolean> {
  try {
    return (await authConfig()).audio_delivery === "device";
  } catch {
    return false;
  }
}

// --------------------------------------------------------------------------- sync

/** The device keys each chapter by its audio file (a re-narration is a new file). */
export function trackKey(t: Pick<Track, "audio_id" | "audio_hash">): string {
  return t.audio_id ?? t.audio_hash ?? "";
}

/** "device" or "server"; throws if the server can't be reached (callers retry). */
export async function deliveryMode(): Promise<"device" | "server"> {
  return (await authConfig()).audio_delivery === "device" ? "device" : "server";
}

const inFlight = new Map<string, Promise<boolean>>();

/** Download one chapter into this browser, then tell the server it may delete its copy. */
export function pullTrack(bookId: string, track: Track): Promise<boolean> {
  const key = keyOf(track.chapter_id, trackKey(track));
  const running = inFlight.get(key);
  if (running) return running;
  const job = (async () => {
    if (!track.url || !track.audio_hash) return false;
    if (await getChapter(track.chapter_id, trackKey(track))) {
      await confirm(bookId, track);
      return true;
    }
    const res = await fetch(track.url);
    if (!res.ok) throw new Error(`download failed (${res.status})`);
    const blob = await res.blob();
    if (!blob.size) throw new Error("empty audio");
    await putChapter({
      key,
      bookId,
      chapterId: track.chapter_id,
      hash: trackKey(track),
      format: track.format ?? "mp3",
      size: blob.size,
      savedAt: Date.now(),
      blob,
    });
    await confirm(bookId, track);
    return true;
  })().finally(() => inFlight.delete(key));
  inFlight.set(key, job);
  return job;
}

async function confirm(bookId: string, track: Track) {
  if (!track.on_device && track.audio_hash) await playerApi.audioReceived(bookId, track.chapter_id, track.audio_hash).catch(() => undefined);
}

/**
 * Bring every finished chapter of a book onto this device.
 * Returns how many chapters are here, and how many live on another device.
 */
export async function syncBook(bookId: string, playback?: Playback): Promise<{ local: number; elsewhere: number; total: number }> {
  const pb = playback ?? (await playerApi.playback(bookId));
  let local = 0;
  let elsewhere = 0;
  // Two at a time: quick, without starving playback of bandwidth.
  const queue = [...pb.tracks];
  const worker = async () => {
    for (let t = queue.shift(); t; t = queue.shift()) {
      if (await getChapter(t.chapter_id, trackKey(t))) {
        local++;
        if (!t.on_device) void confirm(bookId, t);
      } else if (t.url) {
        try {
          if (await pullTrack(bookId, t)) local++;
        } catch {
          /* retried on the next sync */
        }
      } else if (t.on_device) {
        elsewhere++;
      }
    }
  };
  await Promise.all([worker(), worker()]);
  return { local, elsewhere, total: pb.tracks.length };
}

/** Join a book's chapters (MP3 frames concatenate cleanly) into one file to keep. */
export async function saveBookAsFile(playback: Playback): Promise<void> {
  const parts: Blob[] = [];
  for (const t of playback.tracks) {
    const c = await getChapter(t.chapter_id, trackKey(t));
    if (!c) throw new Error(`"${t.title}" isn't on this device yet.`);
    parts.push(c.blob);
  }
  const ext = playback.tracks[0]?.format ?? "mp3";
  if (playback.tracks.some((t) => (t.format ?? "mp3") !== "mp3")) {
    throw new Error("Saving one file needs MP3 chapters. Choose MP3 in Voice Studio, or save chapters one by one.");
  }
  const blob = new Blob(parts, { type: "audio/mpeg" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${(playback.book.title || "audiobook").replace(/[\\/:*?"<>|]+/g, " ").trim()}.${ext}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}
