import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lightbulb } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Notice, Skeleton } from "@/components/ui/Feedback";
import { Segmented } from "@/components/ui/Form";
import { toast } from "@/components/ui/Toast";
import { useJob } from "@/hooks/useJob";
import { aiApi } from "@/services/api";
import { errorMessage } from "@/services/http";
import { qk } from "@/services/queryClient";
import type { Insights as InsightsData } from "@/types/api";

type Tab = "summary" | "chapters" | "characters" | "events" | "themes" | "glossary";

/** Optional study aids generated from the text. They never modify the audiobook source. */
export function Insights({ bookId, llmAvailable }: { bookId: string; llmAvailable: boolean }) {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("summary");
  const [jobId, setJobId] = useState<string | null>(null);
  const q = useQuery({ queryKey: qk.insights(bookId), queryFn: () => aiApi.insights(bookId) });
  const create = useMutation({
    mutationFn: () => aiApi.createInsights(bookId),
    onSuccess: (j) => setJobId(j.id),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const job = useJob(jobId, (j) => {
    setJobId(null);
    if (j.status !== "completed") toast.error(j.error?.message ?? "Couldn't generate insights.");
    void qc.invalidateQueries({ queryKey: qk.insights(bookId) });
  });

  const data = q.data;
  const empty = data && !data.short_summary && !data.chapter_summaries.length && !data.characters;

  return (
    <div className="surface p-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 font-medium text-paper-50">
          <Lightbulb className="size-4 text-orchid-400" /> Book insights
        </h2>
        <Button size="sm" onClick={() => create.mutate()} loading={create.isPending || !!jobId} disabled={!llmAvailable || !!jobId}>
          {empty ? "Generate" : "Refresh"}
        </Button>
      </div>
      {!llmAvailable && <p className="mt-2 text-xs text-paper-500">Needs an AI model (LLM_PROVIDER). Summaries are optional and never change the book.</p>}
      {job && <p className="mt-3 text-xs text-paper-400">{job.message} {job.progress ? `· ${Math.round(job.progress)}%` : ""}</p>}
      {q.isPending ? (
        <Skeleton className="mt-4 h-32" />
      ) : q.isError ? (
        <Notice kind="error" className="mt-4">{errorMessage(q.error)}</Notice>
      ) : empty ? (
        <p className="mt-4 text-sm text-paper-500">Summaries, characters, key events, themes and a glossary, written from the book's text.</p>
      ) : (
        <>
          <Segmented<Tab>
            label="Insight type"
            className="mt-4"
            value={tab}
            onChange={setTab}
            options={[
              { value: "summary", label: "Summary" },
              { value: "chapters", label: "Chapters" },
              { value: "characters", label: "Characters" },
              { value: "events", label: "Events" },
              { value: "themes", label: "Themes" },
              { value: "glossary", label: "Glossary" },
            ]}
          />
          <div className="mt-4 max-h-[50vh] overflow-y-auto pr-1 text-sm leading-relaxed text-paper-300">
            <InsightBody tab={tab} data={data!} />
          </div>
        </>
      )}
    </div>
  );
}

function list<T>(obj: Record<string, unknown> | undefined, key: string): T[] {
  const v = obj?.[key];
  return Array.isArray(v) ? (v as T[]) : [];
}

function InsightBody({ tab, data }: { tab: Tab; data: InsightsData }) {
  const none = <p className="text-paper-500">Not generated yet.</p>;
  switch (tab) {
    case "summary":
      return data.short_summary || data.detailed_summary ? (
        <div className="space-y-4">
          {data.short_summary && <p className="text-paper-200">{String(data.short_summary.text ?? "")}</p>}
          {data.detailed_summary && <div className="space-y-3 whitespace-pre-line">{String(data.detailed_summary.text ?? "")}</div>}
        </div>
      ) : (
        none
      );
    case "chapters":
      return data.chapter_summaries.length ? (
        <ol className="space-y-3">
          {data.chapter_summaries.map((c) => (
            <li key={c.chapter_id}>
              <p className="font-medium text-paper-100">{String(c.title ?? "")}</p>
              <p>{String(c.summary ?? "")}</p>
            </li>
          ))}
        </ol>
      ) : (
        none
      );
    case "characters": {
      const items = list<{ name: string; description?: string; role?: string }>(data.characters, "characters");
      return items.length ? (
        <ul className="space-y-3">
          {items.map((c) => (
            <li key={c.name}>
              <span className="font-medium text-paper-100">{c.name}</span>
              {c.role && <span className="text-xs text-paper-500"> · {c.role}</span>}
              {c.description && <p>{c.description}</p>}
            </li>
          ))}
        </ul>
      ) : (
        none
      );
    }
    case "events": {
      const items = list<{ chapter?: string; event: string }>(data.events, "events");
      return items.length ? (
        <ol className="space-y-2">
          {items.map((e, i) => (
            <li key={i}>
              {e.chapter && <span className="text-xs text-orchid-300">{e.chapter} · </span>}
              {e.event}
            </li>
          ))}
        </ol>
      ) : (
        none
      );
    }
    case "themes": {
      const items = list<{ theme: string; explanation?: string }>(data.themes, "themes");
      return items.length ? (
        <ul className="space-y-3">
          {items.map((t) => (
            <li key={t.theme}>
              <span className="font-medium text-paper-100">{t.theme}</span>
              {t.explanation && <p>{t.explanation}</p>}
            </li>
          ))}
        </ul>
      ) : (
        none
      );
    }
    case "glossary": {
      const items = list<{ term: string; definition?: string }>(data.glossary, "terms");
      return items.length ? (
        <dl className="space-y-2">
          {items.map((t) => (
            <div key={t.term}>
              <dt className="font-medium text-paper-100">{t.term}</dt>
              <dd>{t.definition}</dd>
            </div>
          ))}
        </dl>
      ) : (
        none
      );
    }
  }
}
