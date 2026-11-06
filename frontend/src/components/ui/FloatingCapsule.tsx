import type { ReactNode } from "react";
import { cn } from "@/utils/format";

/** A small glass info capsule that drifts on its own slow loop. */
export function FloatingCapsule({ eyebrow, children, className, delay = 0, icon }: { eyebrow: string; children: ReactNode; className?: string; delay?: number; icon?: ReactNode }) {
  return (
    <div
      className={cn(
        "glass pointer-events-none absolute flex items-center gap-2.5 rounded-2xl px-3.5 py-2.5 shadow-[0_10px_40px_-12px_rgb(0_0_0/0.7),inset_0_1px_0_rgb(255_255_255/0.06)] animate-[vx-drift_7s_ease-in-out_infinite]",
        className,
      )}
      style={{ animationDelay: `${delay}s` }}
      aria-hidden
    >
      {icon}
      <div>
        <p className="text-[9px] font-semibold tracking-[0.2em] text-paper-500 uppercase">{eyebrow}</p>
        <p className="text-[13px] font-medium whitespace-nowrap text-paper-100">{children}</p>
      </div>
    </div>
  );
}
