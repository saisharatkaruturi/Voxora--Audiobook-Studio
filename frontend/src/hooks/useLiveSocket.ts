import { useEffect, useRef, useState } from "react";
import { wsUrl } from "@/services/http";

/**
 * Subscribe to a backend WebSocket that pushes JSON snapshots.
 * Reconnects with backoff; falls back gracefully (callers also poll via React Query).
 */
export function useLiveSocket<T>(path: string | null, onMessage?: (data: T) => void): { data: T | null; connected: boolean } {
  const [data, setData] = useState<T | null>(null);
  const [connected, setConnected] = useState(false);
  const handler = useRef(onMessage);
  handler.current = onMessage;

  useEffect(() => {
    if (!path) return;
    let ws: WebSocket | null = null;
    let closed = false;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      if (closed) return;
      try {
        ws = new WebSocket(wsUrl(path));
      } catch {
        return;
      }
      ws.onopen = () => {
        attempt = 0;
        setConnected(true);
      };
      ws.onmessage = (ev) => {
        try {
          const parsed = JSON.parse(ev.data as string) as T & { type?: string };
          if (parsed && parsed.type === "error") return;
          setData(parsed);
          handler.current?.(parsed);
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = (ev) => {
        setConnected(false);
        if (closed || ev.code === 4401) return;
        attempt += 1;
        timer = setTimeout(connect, Math.min(15000, 800 * 2 ** attempt));
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      ws?.close();
    };
  }, [path]);

  return { data, connected };
}
