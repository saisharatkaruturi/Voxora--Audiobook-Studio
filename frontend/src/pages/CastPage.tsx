import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, Pause, Play, Sparkles, UserRound, Users } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Badge, EmptyState, Notice, PageLoader } from "@/components/ui/Feedback";
import { Select, Toggle } from "@/components/ui/Form";
import { toast } from "@/components/ui/Toast";
import { useBookContext } from "@/features/book/BookLayout";
import { useJob } from "@/hooks/useJob";
import { useVoicePreview } from "@/hooks/useVoicePreview";
import { aiApi, booksApi, systemApi, voicesApi } from "@/services/api";
import { errorMessage } from "@/services/http";
import { qk } from "@/services/queryClient";
import type { Book, CastMember, Voice } from "@/types/api";
import { cn } from "@/utils/format";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";

export default function CastPage() {
  const { book } = useBookContext();
  const qc = useQueryClient();
  useDocumentTitle("AI Cast");
  const [useLlm, setUseLlm] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const cast = useQuery({ queryKey: qk.cast(book.id), queryFn: () => aiApi.cast(book.id) });
  const voices = useQuery({ queryKey: qk.voices({ installed: true }), queryFn: () => voicesApi.list({}), staleTime: 60_000 });
  const status = useQuery({ queryKey: qk.status, queryFn: systemApi.status, staleTime: 60_000 });
  const preview = useVoicePreview({ speed: book.narration.speed });

  const analyze = useMutation({
    mutationFn: () => aiApi.analyzeCast(book.id, useLlm),
    onSuccess: (job) => setJobId(job.id),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const job = useJob(jobId, (j) => {
    setJobId(null);
    if (j.status === "completed") toast.success("Dialogue analyzed. Review the cast below.");
    else toast.error(j.error?.message ?? "Cast analysis failed.");
    void qc.invalidateQueries({ queryKey: qk.cast(book.id) });
  });

  const toggleMode = useMutation({
    mutationFn: (on: boolean) => booksApi.update(book.id, { narration: { cast_mode: on } }),
    onSuccess: (b) => {
      qc.setQueryData<Book>(qk.book(book.id), b);
      void qc.invalidateQueries({ queryKey: qk.cast(book.id) });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const assign = useMutation({
    mutationFn: ({ id, provider, voice_id }: { id: string; provider: string; voice_id: string }) => aiApi.updateCast(id, { provider, voice_id }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.cast(book.id) }),
    onError: (e) => toast.error(errorMessage(e)),
  });

  const lang = book.language ?? "en";
  const voiceOptions = useMemo(
    () => (voices.data?.items ?? []).filter((v) => v.installed && (v.language === lang || v.language === "mul")).sort((a, b) => Number(b.is_local) - Number(a.is_local) || a.name.localeCompare(b.name)),
    [voices.data, lang],
  );

  if (cast.isPending) return <PageLoader label="Meeting the characters" />;
  if (cast.isError) return <Notice kind="error">{errorMessage(cast.error)}</Notice>;
  const members = cast.data.items;
  const running = !!jobId;
  const llmReady = status.data?.llm.available;

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="font-display text-3xl font-semibold tracking-tight text-paper-50">AI Cast</h1>
            <Badge tone="amber" icon={<FlaskConical className="size-3" />}>
              Experimental
            </Badge>
          </div>
          <p className="mt-1 max-w-2xl text-sm text-paper-400">
            Give characters their own voices. We only mark where dialogue is and who speaks it. The story's text is never changed.
          </p>
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
        <div className="space-y-6">
          <div className="surface p-5">
            <Toggle
              checked={book.narration.cast_mode}
              onChange={(v) => toggleMode.mutate(v)}
              disabled={toggleMode.isPending || (!members.length && !book.narration.cast_mode)}
              label="Use AI Cast when generating"
              description={members.length ? "Dialogue is read by each character's voice; narration by the Narrator voice." : "Analyze the dialogue first."}
            />
          </div>

          {members.length === 0 ? (
            <EmptyState icon={<Users className="size-6" />} title="No cast yet">
              Analyze the book to find dialogue and the characters who speak it. Works best on fiction with quoted dialogue.
            </EmptyState>
          ) : (
            <ul className="space-y-2" aria-label="Cast">
              {members.map((m) => (
                <CastRow
                  key={m.id}
                  member={m}
                  voices={voiceOptions}
                  previewState={m.provider && m.voice_id ? preview.stateOf(m.provider, m.voice_id) : "idle"}
                  onPreview={() => {
                    const v = voiceOptions.find((x) => x.provider === m.provider && x.id === m.voice_id);
                    if (v) void preview.toggle(v, sampleLine(cast.data.sample, m.name));
                  }}
                  onAssign={(provider, voice_id) => assign.mutate({ id: m.id, provider, voice_id })}
                />
              ))}
            </ul>
          )}
        </div>

        <aside className="space-y-4">
          <div className="surface space-y-4 p-5">
            <h2 className="font-medium text-paper-50">Analyze dialogue</h2>
            <Toggle
              checked={useLlm}
              onChange={setUseLlm}
              disabled={!llmReady}
              label="Refine with AI model"
              description={llmReady ? `Uses ${status.data?.llm.model ?? "the configured model"} to attribute unclear lines. Slower.` : "No AI model is available; heuristics only."}
            />
            <Button variant="primary" className="w-full" icon={<Sparkles className="size-4" />} onClick={() => analyze.mutate()} loading={analyze.isPending || running} disabled={running}>
              {members.length ? "Re-analyze" : "Analyze dialogue"}
            </Button>
            {job && job.status !== "completed" && <p className="text-xs text-paper-400">{job.message}</p>}
            {members.length > 0 && <p className="text-[11px] text-paper-500">Re-analyzing keeps voices you assigned yourself.</p>}
          </div>

          {cast.data.sample.length > 0 && (
            <div className="surface p-5">
              <h2 className="eyebrow mb-3">Detected dialogue</h2>
              <ul className="space-y-3">
                {cast.data.sample.slice(0, 8).map((s, i) => (
                  <li key={i} className="text-sm">
                    <span className="text-xs font-medium text-orchid-300">{s.speaker ?? "Unknown"}</span>
                    <p className="mt-0.5 font-display text-paper-300">{String(s.text ?? "")}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

function sampleLine(sample: { speaker?: string | null; text?: string }[], name: string): string | undefined {
  const line = sample.find((s) => s.speaker === name)?.text;
  return line ? String(line).replace(/^["“«‘]|["”»’]$/g, "").slice(0, 300) : undefined;
}

function CastRow({
  member,
  voices,
  previewState,
  onPreview,
  onAssign,
}: {
  member: CastMember;
  voices: Voice[];
  previewState: "idle" | "loading" | "playing";
  onPreview: () => void;
  onAssign: (provider: string, voiceId: string) => void;
}) {
  const value = member.provider && member.voice_id ? `${member.provider}|${member.voice_id}` : "";
  return (
    <li className="surface flex flex-wrap items-center gap-4 p-4">
      <div className={cn("flex size-10 items-center justify-center rounded-full", member.role === "narrator" ? "bg-orchid-500/15 text-orchid-300" : "bg-white/[0.06] text-paper-300")}>
        <UserRound className="size-4" />
      </div>
      <div className="min-w-32 flex-1">
        <p className="font-medium text-paper-50">{member.name}</p>
        <p className="text-xs text-paper-500">
          {member.role === "narrator" ? "Narration" : `${member.line_count} line${member.line_count === 1 ? "" : "s"}`}
          {member.gender_hint && member.gender_hint !== "unknown" ? ` · ${member.gender_hint}` : ""}
          {member.auto_assigned ? " · auto-assigned" : " · your choice"}
        </p>
      </div>
      <div className="flex w-full items-center gap-2 sm:w-80">
        <div className="flex-1">
          <Select
            aria-label={`Voice for ${member.name}`}
            value={value}
            onChange={(e) => {
              const [p, ...rest] = e.target.value.split("|");
              if (p) onAssign(p, rest.join("|"));
            }}
          >
            {!value && <option value="">Choose a voice</option>}
            {value && !voices.some((v) => `${v.provider}|${v.id}` === value) && <option value={value}>{member.voice_id}</option>}
            {voices.map((v) => (
              <option key={`${v.provider}|${v.id}`} value={`${v.provider}|${v.id}`}>
                {v.name} · {v.gender ?? "voice"} · {v.is_local ? "local" : "cloud"}
              </option>
            ))}
          </Select>
        </div>
        <Button size="sm" variant="secondary" onClick={onPreview} disabled={!value} aria-label={`Preview ${member.name}'s voice`}>
          {previewState === "playing" ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
        </Button>
      </div>
    </li>
  );
}
