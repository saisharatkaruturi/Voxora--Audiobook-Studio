import { useCallback, useEffect, useRef, useState } from "react";
import { voicesApi } from "@/services/api";
import { errorMessage } from "@/services/http";
import { toast } from "@/components/ui/Toast";
import { usePlayer } from "@/stores/player";

/**
 * Play real synthesized previews (one at a time). The server synthesizes the
 * sample with the actual engine and caches it, so repeated previews are instant.
 */
export function useVoicePreview(opts: { bookId?: string; speed?: number; pitch?: number } = {}) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const [active, setActive] = useState<{ key: string; state: "loading" | "playing" } | null>(null);
  const token = useRef(0);

  const stop = useCallback(() => {
    token.current++;
    audio.current?.pause();
    audio.current = null;
    setActive(null);
  }, []);

  useEffect(() => stop, [stop]);

  const toggle = useCallback(
    async (voice: { provider: string; id: string; language?: string | null }, text?: string) => {
      const key = `${voice.provider}:${voice.id}`;
      if (active?.key === key) {
        stop();
        return;
      }
      stop();
      const my = ++token.current;
      setActive({ key, state: "loading" });
      try {
        const { url } = await voicesApi.preview({
          provider: voice.provider,
          voice_id: voice.id,
          speed: opts.speed ?? 1,
          pitch: opts.pitch ?? 0,
          language: voice.language && voice.language !== "mul" ? voice.language : undefined,
          book_id: text ? undefined : opts.bookId,
          text,
        });
        if (my !== token.current) return;
        usePlayer.getState().pause();
        const a = new Audio(url);
        audio.current = a;
        a.onended = () => my === token.current && setActive(null);
        await a.play();
        if (my === token.current) setActive({ key, state: "playing" });
      } catch (err) {
        if (my === token.current) {
          setActive(null);
          toast.error(`Preview failed: ${errorMessage(err)}`);
        }
      }
    },
    [active, opts.bookId, opts.pitch, opts.speed, stop],
  );

  const stateOf = (provider: string, id: string): "idle" | "loading" | "playing" => (active?.key === `${provider}:${id}` ? active.state : "idle");

  return { toggle, stop, stateOf };
}
