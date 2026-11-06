import { useState } from "react";
import { ArrowDown, ArrowUp, Check, GripVertical, Merge, RotateCcw, VolumeX } from "lucide-react";
import { Button } from "@/components/ui/Button";
import type { Chapter } from "@/types/api";
import { cn, kindLabel } from "@/utils/format";

interface Props {
  chapters: Chapter[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onReorder: (ids: string[]) => void;
  onMerge: (ids: string[]) => void;
  busy: boolean;
}

/** Book structure: select, multi-select to merge, and reorder by drag or keyboard (arrow buttons). */
export function ChapterList({ chapters, selectedId, onSelect, onReorder, onMerge, busy }: Props) {
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [dragId, setDragId] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);

  const move = (from: number, to: number) => {
    if (to < 0 || to >= chapters.length) return;
    const ids = chapters.map((c) => c.id);
    const [id] = ids.splice(from, 1);
    ids.splice(to, 0, id);
    onReorder(ids);
  };

  const toggle = (id: string) => {
    const next = new Set(checked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setChecked(next);
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-3 pt-3 pb-2">
        <p className="eyebrow">Book structure</p>
        <span className="text-xs text-paper-500">{chapters.filter((c) => c.include_in_audio).length} narrated</span>
      </div>
      {checked.size > 0 && (
        <div className="mx-2 mb-2 flex items-center justify-between gap-2 rounded-xl bg-orchid-500/10 px-3 py-2">
          <span className="text-xs text-orchid-300">{checked.size} selected</span>
          <div className="flex gap-1">
            <Button size="sm" variant="ghost" onClick={() => setChecked(new Set())}>
              Clear
            </Button>
            <Button
              size="sm"
              variant="primary"
              icon={<Merge className="size-3.5" />}
              disabled={checked.size < 2 || busy}
              onClick={() => {
                onMerge([...checked]);
                setChecked(new Set());
              }}
            >
              Merge
            </Button>
          </div>
        </div>
      )}
      <ol className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-3" aria-label="Chapters">
        {chapters.map((c, i) => {
          const active = c.id === selectedId;
          return (
            <li
              key={c.id}
              draggable
              onDragStart={(e) => {
                setDragId(c.id);
                e.dataTransfer.effectAllowed = "move";
              }}
              onDragOver={(e) => {
                e.preventDefault();
                setOverId(c.id);
              }}
              onDragEnd={() => {
                setDragId(null);
                setOverId(null);
              }}
              onDrop={(e) => {
                e.preventDefault();
                if (dragId && dragId !== c.id) move(chapters.findIndex((x) => x.id === dragId), i);
                setDragId(null);
                setOverId(null);
              }}
              className={cn(
                "group relative flex items-center gap-1.5 rounded-xl pr-1 pl-1 transition-colors",
                active ? "bg-white/[0.07]" : "hover:bg-white/[0.035]",
                dragId === c.id && "opacity-40",
                overId === c.id && dragId && dragId !== c.id && "ring-1 ring-orchid-500/50",
              )}
            >
              <GripVertical className="size-3.5 shrink-0 cursor-grab text-paper-500 opacity-0 group-hover:opacity-100" aria-hidden />
              <input
                type="checkbox"
                checked={checked.has(c.id)}
                onChange={() => toggle(c.id)}
                aria-label={`Select ${c.title} for merging`}
                className="size-3.5 shrink-0 accent-orchid-500"
              />
              <button type="button" onClick={() => onSelect(c.id)} aria-current={active ? "true" : undefined} className="min-w-0 flex-1 py-2.5 pl-1.5 text-left">
                <span className="flex items-center gap-2">
                  <span className={cn("truncate text-[13px]", active ? "font-medium text-paper-50" : c.include_in_audio ? "text-paper-200" : "text-paper-500 line-through decoration-paper-500/40")}>
                    {c.title}
                  </span>
                </span>
                <span className="mt-0.5 flex items-center gap-1.5 text-[11px] text-paper-500">
                  <span>{kindLabel(c.kind)}</span>·<span className="tabular-nums">{c.word_count.toLocaleString()} words</span>
                  {!c.include_in_audio && <VolumeX className="size-3" aria-label="Not narrated" />}
                  {c.audio_status === "done" && !c.stale && <Check className="size-3 text-sage-400" aria-label="Audio ready" />}
                  {c.stale && <RotateCcw className="size-3 text-orchid-400" aria-label="Edited since audio was made" />}
                  {typeof c.detection?.confidence === "number" && c.detection.confidence < 0.5 && <span className="text-orchid-400">low confidence</span>}
                </span>
              </button>
              <div className="flex flex-col opacity-0 group-focus-within:opacity-100 group-hover:opacity-100">
                <button type="button" onClick={() => move(i, i - 1)} disabled={i === 0 || busy} aria-label={`Move ${c.title} up`} className="rounded p-0.5 text-paper-500 hover:text-paper-100 disabled:opacity-30">
                  <ArrowUp className="size-3" />
                </button>
                <button type="button" onClick={() => move(i, i + 1)} disabled={i === chapters.length - 1 || busy} aria-label={`Move ${c.title} down`} className="rounded p-0.5 text-paper-500 hover:text-paper-100 disabled:opacity-30">
                  <ArrowDown className="size-3" />
                </button>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
