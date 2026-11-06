import { useEffect } from "react";
import { booksApi } from "@/services/api";
import { deliveryMode, requestPersistence, syncBook } from "@/services/deviceAudio";
import { useAuth } from "@/stores/auth";

const INTERVAL_MS = 15_000;

/**
 * Device delivery: while VOXORA is open, move every finished chapter onto this
 * device (and off the server). Runs app-wide, so conversions keep landing here
 * whichever page the listener is on.
 */
export function useDeviceSync() {
  const token = useAuth((s) => s.token);

  useEffect(() => {
    if (!token) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    // Books already fully here, by how many chapters had audio when we last looked.
    const settled = new Map<string, number>();

    const tick = async () => {
      if (stopped) return;
      try {
        if ((await deliveryMode()) === "server") return; // nothing to collect: stop polling (throws -> retried below)
        void requestPersistence();
        const { items } = await booksApi.list({ limit: 200 });
        for (const book of items) {
          if (stopped) return;
          const ready = book.chapters_with_audio ?? 0;
          if (!ready || settled.get(book.id) === ready) continue;
          const r = await syncBook(book.id).catch(() => null);
          // Settled when nothing is left to fetch (chapters held elsewhere can't be fetched).
          if (r && r.local + r.elsewhere >= r.total && book.status !== "generating") settled.set(book.id, ready);
        }
      } catch {
        /* offline or signed out: try again next tick */
      }
      if (!stopped) timer = setTimeout(() => void tick(), INTERVAL_MS);
    };
    void tick();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [token]);
}
