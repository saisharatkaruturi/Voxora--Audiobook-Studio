import type { ReactNode } from "react";
import { Field, Segmented, Select, Toggle } from "@/components/ui/Form";
import type { Narration, TTSProviderInfo } from "@/types/api";

const SPEEDS = [0.75, 1, 1.1, 1.25, 1.5, 1.75, 2];

function Slider({ label, value, min, max, step, unit, onChange, disabled, hint }: { label: string; value: number; min: number; max: number; step: number; unit: string; onChange: (v: number) => void; disabled?: boolean; hint?: ReactNode }) {
  const id = `s-${label.replace(/\W/g, "")}`;
  return (
    <div className={disabled ? "opacity-45" : ""}>
      <div className="mb-2 flex items-baseline justify-between">
        <label htmlFor={id} className="text-[13px] font-medium text-paper-300">
          {label}
        </label>
        <span className="text-xs text-paper-400 tabular-nums">
          {value}
          {unit}
        </span>
      </div>
      <input id={id} type="range" className="range" min={min} max={max} step={step} value={value} disabled={disabled} onChange={(e) => onChange(Number(e.target.value))} />
      {hint && <p className="mt-1 text-[11px] text-paper-500">{hint}</p>}
    </div>
  );
}

/** Voice and audio settings for a book. Every change is saved immediately. */
export function NarrationSettings({ n, provider, onChange }: { n: Narration; provider?: TTSProviderInfo; onChange: (patch: Partial<Narration>) => void }) {
  return (
    <div className="space-y-8">
      <section className="space-y-5">
        <h3 className="eyebrow">Voice</h3>
        <div>
          <p className="mb-2 text-[13px] font-medium text-paper-300">Narration speed</p>
          <Segmented<number> label="Narration speed" value={n.speed} onChange={(v) => onChange({ speed: v })} options={SPEEDS.map((s) => ({ value: s, label: `${s}×` }))} />
          <p className="mt-1.5 text-[11px] text-paper-500">Baked into the audio. You can still change playback speed in the player.</p>
        </div>
        <Slider
          label="Pitch"
          value={n.pitch}
          min={-10}
          max={10}
          step={1}
          unit=""
          onChange={(v) => onChange({ pitch: v })}
          disabled={provider ? !provider.supports_pitch : false}
          hint={provider && !provider.supports_pitch ? `${provider.display_name} doesn't support pitch changes.` : undefined}
        />
        <Slider label="Volume" value={Math.round(n.volume * 100)} min={0} max={200} step={5} unit="%" onChange={(v) => onChange({ volume: v / 100 })} />
      </section>

      <section className="space-y-5">
        <h3 className="eyebrow">Pauses</h3>
        <Slider label="Between sentences" value={n.sentence_pause_ms} min={0} max={1500} step={50} unit=" ms" onChange={(v) => onChange({ sentence_pause_ms: v })} />
        <Slider label="Between paragraphs" value={n.paragraph_pause_ms} min={0} max={3000} step={50} unit=" ms" onChange={(v) => onChange({ paragraph_pause_ms: v })} />
        <Slider label="After headings" value={n.heading_pause_ms} min={0} max={4000} step={100} unit=" ms" onChange={(v) => onChange({ heading_pause_ms: v })} />
        <Slider label="End of chapter" value={n.chapter_pause_ms} min={0} max={6000} step={100} unit=" ms" onChange={(v) => onChange({ chapter_pause_ms: v })} />
      </section>

      <section className="space-y-4">
        <h3 className="eyebrow">Narration</h3>
        <Toggle
          checked={n.narration_cleanup}
          onChange={(v) => onChange({ narration_cleanup: v })}
          label="Narration Cleanup"
          description="Speaks abbreviations, numbers, dates, symbols and URLs naturally. Never rewrites, summarizes or paraphrases."
        />
        <Toggle
          checked={n.ai_ocr_repair}
          onChange={(v) => onChange({ ai_ocr_repair: v })}
          label="AI OCR repair"
          description="Uses the configured AI model to fix obvious OCR misreadings before speaking. Slower; only useful for scanned books."
        />
        <Toggle checked={n.announce_chapter_titles} onChange={(v) => onChange({ announce_chapter_titles: v })} label="Read chapter titles aloud" />
      </section>

      <section className="space-y-4">
        <h3 className="eyebrow">Audio processing</h3>
        <Toggle checked={n.normalize} onChange={(v) => onChange({ normalize: v })} label="Normalize loudness" description="Even volume across chapters." />
        <Toggle checked={n.compress} onChange={(v) => onChange({ compress: v })} label="Gentle compression" description="Evens out quiet and loud passages. Good for noisy places." />
        <Toggle checked={n.shorten_long_pauses} onChange={(v) => onChange({ shorten_long_pauses: v })} label="Remove excessive silence" description="Shortens unnatural gaps while keeping intentional pauses." />
        <Toggle checked={n.build_full_audiobook} onChange={(v) => onChange({ build_full_audiobook: v })} label="Also build a single full-book file" description="Chapter files are always created." />
        <div className="grid grid-cols-2 gap-3 pt-1">
          <Field label="Format" htmlFor="fmt">
            <Select id="fmt" value={n.format} onChange={(e) => onChange({ format: e.target.value as Narration["format"] })}>
              <option value="mp3">MP3</option>
              <option value="m4a">M4A (AAC)</option>
              <option value="wav">WAV (large)</option>
            </Select>
          </Field>
          <Field label="Bitrate" htmlFor="br">
            <Select id="br" value={n.bitrate} disabled={n.format === "wav"} onChange={(e) => onChange({ bitrate: e.target.value })}>
              {["48k", "64k", "96k", "128k", "160k", "192k"].map((b) => (
                <option key={b} value={b}>
                  {b.replace("k", " kbps")}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      </section>
    </div>
  );
}
