import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme, type ThemeChoice } from "@/stores/theme";
import { cn } from "@/utils/format";

/** Round sun/moon switch for the navigation bar. */
export function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggle } = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={`Switch to ${next} mode`}
      title={`Switch to ${next} mode`}
      className={cn("relative flex size-9 items-center justify-center overflow-hidden rounded-full text-paper-300 transition-colors hover:bg-white/[0.07] hover:text-paper-50", className)}
    >
      <Sun className={cn("absolute size-4 transition-all duration-500 ease-[var(--ease-out-soft)]", theme === "light" ? "rotate-0 opacity-100" : "-rotate-90 scale-50 opacity-0")} aria-hidden />
      <Moon className={cn("absolute size-4 transition-all duration-500 ease-[var(--ease-out-soft)]", theme === "dark" ? "rotate-0 opacity-100" : "rotate-90 scale-50 opacity-0")} aria-hidden />
    </button>
  );
}

const OPTIONS: { value: ThemeChoice; label: string; icon: typeof Sun; hint: string }[] = [
  { value: "light", label: "Light", icon: Sun, hint: "Lavender dawn" },
  { value: "dark", label: "Dark", icon: Moon, hint: "Starry night" },
  { value: "system", label: "Device", icon: Monitor, hint: "Match your system" },
];

/** Three large preview cards for Settings → Appearance. */
export function ThemePicker() {
  const { choice, setChoice } = useTheme();
  return (
    <div role="radiogroup" aria-label="Theme" className="grid grid-cols-3 gap-3">
      {OPTIONS.map(({ value, label, icon: Icon, hint }) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={choice === value}
          onClick={() => setChoice(value)}
          className={cn(
            "group overflow-hidden rounded-2xl border text-left transition-all duration-300 hover:-translate-y-0.5",
            choice === value ? "border-orchid-500/60 shadow-[var(--shadow-glow)]" : "border-white/[0.08] hover:border-white/[0.18]",
          )}
        >
          <div
            className="relative h-20"
            style={{
              background:
                value === "light"
                  ? "#f2f0e9"
                  : value === "dark"
                    ? "#0b3048"
                    : "linear-gradient(90deg, #f2f0e9 0 50%, #0b3048 50% 100%)",
            }}
          >
            <span className={cn("absolute top-3 left-3 h-2 w-12 rounded-full", value === "dark" ? "bg-[#f2f0e9]/80" : "bg-[#0b3048]/70")} />
            <span className="absolute top-7 left-3 h-1.5 w-20 rounded-full bg-[#b9f12f]" />
            <span className={cn("absolute right-3 bottom-3 h-6 w-10 rounded-lg", value === "dark" ? "bg-[rgb(255_255_255/0.1)]" : "bg-[rgb(255_255_255/0.85)] shadow")} />
          </div>
          <div className="flex items-center gap-2 px-3 py-2.5">
            <Icon className="size-4 text-orchid-400" aria-hidden />
            <div>
              <p className="text-sm font-medium text-paper-50">{label}</p>
              <p className="text-[11px] text-paper-500">{hint}</p>
            </div>
          </div>
        </button>
      ))}
    </div>
  );
}
