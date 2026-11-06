import { AlertCircle, CheckCircle2, Clock, Loader2, PenLine, Upload } from "lucide-react";
import { Badge } from "@/components/ui/Feedback";
import type { BookStatus } from "@/types/api";

const MAP: Record<BookStatus, { label: string; tone: "neutral" | "amber" | "sage" | "rose" | "sky"; icon: typeof Clock }> = {
  uploaded: { label: "Uploaded", tone: "neutral", icon: Upload },
  analyzing: { label: "Analyzing", tone: "sky", icon: Loader2 },
  review: { label: "Ready to narrate", tone: "amber", icon: PenLine },
  generating: { label: "Generating", tone: "sky", icon: Loader2 },
  ready: { label: "Ready", tone: "sage", icon: CheckCircle2 },
  failed: { label: "Failed", tone: "rose", icon: AlertCircle },
};

export function StatusBadge({ status, paused }: { status: BookStatus; paused?: boolean }) {
  const m = MAP[status] ?? MAP.uploaded;
  const Icon = m.icon;
  if (paused) return <Badge tone="amber" icon={<Clock className="size-3" />}>Paused</Badge>;
  return (
    <Badge tone={m.tone} icon={<Icon className={status === "analyzing" || status === "generating" ? "size-3 animate-spin" : "size-3"} />}>
      {m.label}
    </Badge>
  );
}
