import { create } from "zustand";

export type ThemeChoice = "system" | "light" | "dark";
export type Theme = "light" | "dark";

const KEY = "vx.theme";

function stored(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" || v === "system" ? v : "dark";
  } catch {
    return "dark";
  }
}

const media = typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null;
const resolve = (choice: ThemeChoice): Theme => (choice === "system" ? (media?.matches ? "light" : "dark") : choice);

function apply(theme: Theme) {
  const root = document.documentElement;
  root.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "light" ? "#f6f3fb" : "#140b26");
}

interface ThemeState {
  choice: ThemeChoice;
  theme: Theme;
  setChoice: (c: ThemeChoice) => void;
  toggle: () => void;
}

/** Light / dark / follow-the-device, remembered per device. index.html applies it before first paint. */
export const useTheme = create<ThemeState>((set, get) => {
  const choice = stored();
  const theme = resolve(choice);
  if (typeof document !== "undefined") apply(theme);
  media?.addEventListener("change", () => {
    if (get().choice === "system") {
      const t = resolve("system");
      apply(t);
      set({ theme: t });
    }
  });
  return {
    choice,
    theme,
    setChoice: (c) => {
      try {
        localStorage.setItem(KEY, c);
      } catch {
        /* ignore */
      }
      const t = resolve(c);
      apply(t);
      set({ choice: c, theme: t });
    },
    toggle: () => get().setChoice(get().theme === "dark" ? "light" : "dark"),
  };
});
