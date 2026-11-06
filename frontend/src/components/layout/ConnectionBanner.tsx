import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { WifiOff } from "lucide-react";
import { brand } from "@/config/brand";
import { useConnection } from "@/stores/connection";

/** Shown while the server can't be reached; polls until it's back, then refreshes the page's data. */
export function ConnectionBanner() {
  const offline = useConnection((s) => s.offline);
  const qc = useQueryClient();
  useEffect(() => {
    if (!offline) return;
    let stop = false;
    const tick = async () => {
      try {
        const r = await fetch("/api/health", { cache: "no-store" });
        if (r.ok && !stop) {
          useConnection.getState().setOffline(false);
          void qc.invalidateQueries();
          return;
        }
      } catch {
        /* still down */
      }
      if (!stop) setTimeout(tick, 2000);
    };
    const t = setTimeout(tick, 1500);
    return () => {
      stop = true;
      clearTimeout(t);
    };
  }, [offline, qc]);
  if (!offline) return null;
  return (
    <div role="status" className="fixed inset-x-0 top-20 z-[90] flex justify-center px-4">
      <div className="glass flex items-center gap-3 rounded-full px-4 py-2 text-sm text-paper-100 shadow-2xl">
        <WifiOff className="size-4 text-amber-300" aria-hidden />
        Reconnecting to {brand.name}… your books and progress are safe.
      </div>
    </div>
  );
}
