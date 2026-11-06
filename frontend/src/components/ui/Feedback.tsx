import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, Loader2, XCircle } from "lucide-react";
import { cn } from "@/utils/format";
import { BrandMark } from "@/components/brand/BrandMark";

type Tone = "neutral" | "amber" | "sage" | "rose" | "sky";

const tones: Record<Tone, string> = {
  neutral: "bg-white/[0.06] text-paper-300 border-white/[0.06]",
  amber: "bg-orchid-500/12 text-orchid-300 border-orchid-500/20",
  sage: "bg-sage-400/12 text-sage-400 border-sage-400/20",
  rose: "bg-rose-400/12 text-rose-400 border-rose-400/20",
  sky: "bg-sky-400/12 text-sky-400 border-sky-400/20",
};

export function Badge({ tone = "neutral", children, className, icon }: { tone?: Tone; children: ReactNode; className?: string; icon?: ReactNode }) {
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap", tones[tone], className)}>
      {icon}
      {children}
    </span>
  );
}

export function Spinner({ className, label = "Loading" }: { className?: string; label?: string }) {
  return <Loader2 className={cn("size-5 animate-spin text-paper-400", className)} aria-label={label} role="status" />;
}

/** VOXORA loader: the mark's waveform breathes while a contextual message explains the wait. */
export function PageLoader({ label = "Opening your story" }: { label?: string }) {
  return (
    <div className="flex min-h-[40vh] items-center justify-center" role="status">
      <div className="flex flex-col items-center gap-4 text-sm text-paper-400">
        <BrandMark className="size-10 opacity-90" animated />
        <span>{label}…</span>
      </div>
    </div>
  );
}

const noticeIcon = {
  info: Info,
  warning: AlertTriangle,
  error: XCircle,
  success: CheckCircle2,
};
const noticeTone = {
  info: "border-sky-400/20 bg-sky-400/[0.06] text-sky-400",
  warning: "border-amber-400/25 bg-amber-400/[0.07] text-amber-300",
  error: "border-rose-400/25 bg-rose-400/[0.07] text-rose-400",
  success: "border-sage-400/25 bg-sage-400/[0.07] text-sage-400",
};

export function Notice({
  kind = "info",
  title,
  children,
  action,
  className,
}: {
  kind?: keyof typeof noticeIcon;
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const Icon = noticeIcon[kind];
  return (
    <div role={kind === "error" ? "alert" : "status"} className={cn("flex gap-3 rounded-2xl border px-4 py-3", noticeTone[kind], className)}>
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1 text-sm">
        {title && <p className="font-medium text-paper-100">{title}</p>}
        {children && <div className={cn("text-paper-300", title && "mt-0.5")}>{children}</div>}
      </div>
      {action && <div className="shrink-0 self-center">{action}</div>}
    </div>
  );
}

export function EmptyState({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="surface flex flex-col items-center px-6 py-14 text-center">
      {icon && <div className="mb-4 flex size-14 items-center justify-center rounded-2xl bg-white/[0.05] text-paper-300">{icon}</div>}
      <h3 className="font-display text-xl text-paper-50">{title}</h3>
      {children && <div className="mt-2 max-w-md text-sm leading-relaxed text-paper-400">{children}</div>}
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}

export function ProgressBar({ value, className, tone = "amber", label }: { value: number; className?: string; tone?: "amber" | "paper" | "sage"; label?: string }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-white/[0.08]", className)}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(pct)}
      aria-label={label}
    >
      <div
        className={cn(
          "h-full rounded-full transition-[width] duration-500 ease-[var(--ease-out-soft)]",
          tone === "amber" && "bg-orchid-500",
          tone === "paper" && "bg-paper-100",
          tone === "sage" && "bg-sage-400",
        )}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse-soft rounded-xl bg-white/[0.05]", className)} aria-hidden />;
}
