import { useEffect } from "react";
import { SPEEDS, usePlayer } from "@/stores/player";

export const SHORTCUTS: [string, string][] = [
  ["Space / K", "Play or pause"],
  ["← / J", "Back 15 seconds"],
  ["→ / L", "Forward 30 seconds"],
  ["Shift + ← / →", "Previous / next chapter"],
  ["[ / ]", "Slower / faster"],
  ["M", "Mute"],
];

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

/** Keyboard control for the player, so it is fully usable without a mouse. */
export function usePlayerShortcuts(enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target)) return;
      const p = usePlayer.getState();
      if (!p.playback) return;
      const target = e.target as HTMLElement;
      // Let focused buttons handle Space/Enter themselves.
      if ((e.key === " " || e.key === "Enter") && (target.tagName === "BUTTON" || target.getAttribute("role") === "button")) return;
      const idx = SPEEDS.indexOf(p.rate as (typeof SPEEDS)[number]);
      switch (e.key) {
        case " ":
        case "k":
          p.toggle();
          break;
        case "ArrowLeft":
        case "j":
          if (e.shiftKey) p.previous();
          else p.skip(-15);
          break;
        case "ArrowRight":
        case "l":
          if (e.shiftKey) p.next();
          else p.skip(30);
          break;
        case "[":
          p.setRate(SPEEDS[Math.max(0, (idx < 0 ? 1 : idx) - 1)]);
          break;
        case "]":
          p.setRate(SPEEDS[Math.min(SPEEDS.length - 1, (idx < 0 ? 1 : idx) + 1)]);
          break;
        case "m":
          p.toggleMute();
          break;
        default:
          return;
      }
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled]);
}
