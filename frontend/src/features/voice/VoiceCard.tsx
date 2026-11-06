import { Check, Cloud, Download, HardDrive, Pause, Play } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Badge, Spinner } from "@/components/ui/Feedback";
import { VoiceWaveform } from "@/components/audio/AudioWaveform";
import type { Voice } from "@/types/api";
import { cn, formatBytes } from "@/utils/format";
import { languageName } from "@/utils/languages";

export function VoiceCard({
  voice,
  selected,
  previewState,
  onPreview,
  onSelect,
  onInstall,
  installing,
}: {
  voice: Voice;
  selected: boolean;
  previewState: "idle" | "loading" | "playing";
  onPreview: () => void;
  onSelect: () => void;
  onInstall?: () => void;
  installing?: boolean;
}) {
  const label = `${voice.name}${voice.quality ? ` (${voice.quality})` : ""}${voice.locale ? `, ${voice.locale}` : ""}`;
  const size = typeof voice.meta?.size_bytes === "number" ? (voice.meta.size_bytes as number) : null;
  return (
    <div
      className={cn(
        "group relative flex flex-col rounded-2xl border p-4 transition-colors",
        selected ? "border-orchid-500/50 bg-orchid-500/[0.06]" : "border-white/[0.06] bg-white/[0.02] hover:border-white/[0.12]",
      )}
    >
      <div className="flex items-start gap-3">
        <button
          type="button"
          onClick={onPreview}
          disabled={!voice.installed}
          aria-label={previewState === "playing" ? `Stop preview of ${label}` : `Preview ${label}`}
          className={cn(
            "flex size-11 shrink-0 items-center justify-center rounded-full transition-colors disabled:opacity-40",
            previewState === "playing" ? "bg-orchid-500 text-ink-950" : "bg-white/[0.07] text-paper-100 hover:bg-white/[0.12]",
          )}
        >
          {previewState === "loading" ? <Spinner className="size-4 text-current" /> : previewState === "playing" ? <Pause className="size-4 fill-current" /> : <Play className="size-4 translate-x-px fill-current" />}
        </button>
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-2 font-medium text-paper-50">
            <span className="truncate">{voice.name}</span>
            {selected && <Check className="size-4 shrink-0 text-orchid-400" aria-label="Selected" />}
          </p>
          <p className="truncate text-xs text-paper-400">{voice.accent || languageName(voice.language, voice.language_name)}</p>
        </div>
      </div>
      <VoiceWaveform active={previewState === "playing"} className="mt-3 h-6" />
      <div className="mt-3 flex flex-wrap gap-1.5">
        <Badge icon={voice.is_local ? <HardDrive className="size-3" /> : <Cloud className="size-3" />} tone={voice.is_local ? "sage" : "sky"}>
          {voice.is_local ? "Local" : "Cloud"}
        </Badge>
        {voice.gender && <Badge>{voice.gender[0].toUpperCase() + voice.gender.slice(1)}</Badge>}
        {voice.quality && <Badge>{voice.quality}</Badge>}
        {voice.language === "mul" && <Badge tone="amber">Multilingual</Badge>}
        {voice.style && <Badge className="max-w-full truncate">{voice.style}</Badge>}
      </div>
      <div className="mt-4 flex items-center justify-between gap-2 pt-1">
        <span className="truncate text-[11px] text-paper-500">{voice.provider_name}</span>
        {voice.installed ? (
          <Button size="sm" variant={selected ? "subtle" : "secondary"} onClick={onSelect} disabled={selected} aria-label={selected ? `${label} is the narrator` : `Use ${label}`}>
            {selected ? "Narrator" : "Use voice"}
          </Button>
        ) : (
          <Button size="sm" icon={<Download className="size-3.5" />} onClick={onInstall} loading={installing} aria-label={`Install ${label}`}>
            Install{size ? ` · ${formatBytes(size)}` : ""}
          </Button>
        )}
      </div>
    </div>
  );
}
