import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AudioLines, Cloud, HardDrive, Languages, Search, SlidersHorizontal, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Badge, Notice, Skeleton } from "@/components/ui/Feedback";
import { Input, Segmented, Select } from "@/components/ui/Form";
import { Dialog } from "@/components/ui/Dialog";
import { toast } from "@/components/ui/Toast";
import { useBookContext } from "@/features/book/BookLayout";
import { NarrationSettings } from "@/features/voice/NarrationSettings";
import { VoiceCard } from "@/features/voice/VoiceCard";
import { useJob } from "@/hooks/useJob";
import { useVoicePreview } from "@/hooks/useVoicePreview";
import { booksApi, systemApi, voicesApi } from "@/services/api";
import { errorMessage } from "@/services/http";
import { qk } from "@/services/queryClient";
import type { Book, Narration, Voice } from "@/types/api";
import { formatNumber } from "@/utils/format";
import { FEATURED_LANGUAGES, languageName } from "@/utils/languages";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { brand } from "@/config/brand";

type Source = "all" | "local" | "cloud";

export default function VoiceStudioPage() {
  const { book } = useBookContext();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const n = book.narration;
  useDocumentTitle("Voice Studio");
  const bookLang = book.language ?? "en";
  const [language, setLanguage] = useState<string>(bookLang);
  const [source, setSource] = useState<Source>("all");
  const [provider, setProvider] = useState<string>("all");
  const [gender, setGender] = useState<string>("any");
  const [search, setSearch] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [installJob, setInstallJob] = useState<{ id: string; voice: string } | null>(null);

  const providers = useQuery({ queryKey: qk.providers, queryFn: voicesApi.providers, staleTime: 60_000 });
  const voices = useQuery({ queryKey: qk.voices({ catalog: true }), queryFn: () => voicesApi.list({ include_catalog: true }), staleTime: 60_000 });
  const estimate = useQuery({ queryKey: [...qk.estimate(book.id), n.provider, n.voice_id, n.speed], queryFn: () => booksApi.estimate(book.id) });
  const prefs = useQuery({ queryKey: qk.prefs, queryFn: systemApi.preferences, staleTime: 60_000 });
  const preview = useVoicePreview({ bookId: book.id, speed: n.speed, pitch: n.pitch });

  const update = useMutation({
    mutationFn: (patch: Partial<Narration>) => booksApi.update(book.id, { narration: patch }),
    onMutate: (patch) => {
      const prev = qc.getQueryData<Book>(qk.book(book.id));
      if (prev) qc.setQueryData(qk.book(book.id), { ...prev, narration: { ...prev.narration, ...patch } });
      return { prev };
    },
    onSuccess: (b) => qc.setQueryData(qk.book(book.id), b),
    onError: (e, _p, ctx) => {
      if (ctx?.prev) qc.setQueryData(qk.book(book.id), ctx.prev);
      toast.error(errorMessage(e));
    },
  });

  const install = useMutation({
    mutationFn: (voice: string) => voicesApi.installPiper(voice),
    onSuccess: (job, voice) => setInstallJob({ id: job.id, voice }),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const installing = useJob(installJob?.id ?? null, (job) => {
    if (job.status === "completed") {
      toast.success("Voice installed. It runs fully offline.");
      void qc.invalidateQueries({ queryKey: ["voices"] });
    } else toast.error(job.error?.message ?? "Voice install failed.");
    setInstallJob(null);
  });

  const generate = useMutation({
    mutationFn: (force: boolean) => booksApi.generate(book.id, { force }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.book(book.id) });
      navigate(`/books/${book.id}/processing`);
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const providerInfo = providers.data?.items.find((p) => p.name === n.provider);
  const all = voices.data?.items ?? [];
  const current = all.find((v) => v.provider === n.provider && v.id === n.voice_id);

  const languageOptions = useMemo(() => {
    const codes = new Set(all.map((v) => v.language).filter((l) => l !== "mul"));
    const featured = FEATURED_LANGUAGES.filter((l) => codes.has(l));
    const rest = [...codes].filter((l) => !FEATURED_LANGUAGES.includes(l)).sort((a, b) => languageName(a).localeCompare(languageName(b)));
    return { featured, rest };
  }, [all]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return all
      .filter((v) => language === "all" || v.language === language || v.language === "mul" || v.languages.includes(language))
      .filter((v) => source === "all" || (source === "local" ? v.is_local : !v.is_local))
      .filter((v) => provider === "all" || v.provider === provider)
      .filter((v) => gender === "any" || v.gender === gender)
      .filter((v) => !q || `${v.name} ${v.accent ?? ""} ${v.locale ?? ""} ${v.style ?? ""}`.toLowerCase().includes(q))
      .sort((a, b) => Number(b.installed) - Number(a.installed) || Number(b.is_local) - Number(a.is_local) || Number(b.language === language) - Number(a.language === language) || a.name.localeCompare(b.name));
  }, [all, language, source, provider, gender, search]);

  const hasAudio = (book.chapters_with_audio ?? 0) > 0;
  const otherLangs = book.languages.filter((l) => l !== bookLang);
  const cloud = providerInfo && !providerInfo.is_local;

  return (
    <div className="grid gap-8 xl:grid-cols-[1fr_360px]">
      <div className="min-w-0 space-y-6">
        <header>
          <h1 className="font-display text-3xl font-semibold tracking-tight text-paper-50">{brand.name} Voice Studio</h1>
          <p className="mt-1 text-sm text-paper-400">Give every story a voice. Previews read a passage from your own book.</p>
        </header>

        <div className="surface flex flex-wrap items-center gap-4 p-5">
          <div className="flex size-12 items-center justify-center rounded-2xl bg-orchid-500/15 text-orchid-300">
            <AudioLines className="size-5" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="eyebrow">Narrator</p>
            <p className="mt-0.5 truncate text-lg font-medium text-paper-50">{current?.name ?? n.voice_id ?? "No voice selected"}</p>
            <p className="truncate text-xs text-paper-400">
              {current ? `${current.accent ?? languageName(current.language)} · ${current.provider_name}` : providerInfo?.display_name}
            </p>
          </div>
          {current && (
            <Button onClick={() => void preview.toggle(current)} variant="secondary">
              {preview.stateOf(current.provider, current.id) === "playing" ? "Stop" : "Hear narrator"}
            </Button>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="w-52">
            <Select aria-label="Language" value={language} onChange={(e) => setLanguage(e.target.value)}>
              <option value="all">All languages</option>
              <optgroup label="Featured">
                {languageOptions.featured.map((l) => (
                  <option key={l} value={l}>
                    {languageName(l)}
                    {l === bookLang ? " (book)" : ""}
                  </option>
                ))}
              </optgroup>
              <optgroup label="More languages">
                {languageOptions.rest.map((l) => (
                  <option key={l} value={l}>
                    {languageName(l)}
                    {l === bookLang ? " (book)" : ""}
                  </option>
                ))}
              </optgroup>
            </Select>
          </div>
          <Segmented<Source>
            label="Voice source"
            value={source}
            onChange={setSource}
            options={[
              { value: "all", label: "All" },
              { value: "local", label: <span className="inline-flex items-center gap-1"><HardDrive className="size-3.5" />Local</span> },
              { value: "cloud", label: <span className="inline-flex items-center gap-1"><Cloud className="size-3.5" />Cloud</span> },
            ]}
          />
          <div className="w-40">
            <Select aria-label="Engine" value={provider} onChange={(e) => setProvider(e.target.value)}>
              <option value="all">All engines</option>
              {providers.data?.items.map((p) => (
                <option key={p.name} value={p.name} disabled={!p.available}>
                  {p.display_name}
                  {!p.available ? " (not set up)" : ""}
                </option>
              ))}
            </Select>
          </div>
          <div className="w-32">
            <Select aria-label="Gender" value={gender} onChange={(e) => setGender(e.target.value)}>
              <option value="any">Any voice</option>
              <option value="female">Female</option>
              <option value="male">Male</option>
            </Select>
          </div>
          <div className="relative min-w-40 flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-paper-500" />
            <Input className="pl-9" placeholder="Search voices" aria-label="Search voices" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
        </div>

        {providers.data?.items.some((p) => !p.available) && (
          <p className="text-xs text-paper-500">
            Not set up:{" "}
            {providers.data.items
              .filter((p) => !p.available)
              .map((p) => `${p.display_name} (${p.reason})`)
              .join(" · ")}
          </p>
        )}

        {voices.isPending ? (
          <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-36" />
            ))}
          </div>
        ) : voices.isError ? (
          <Notice kind="error">{errorMessage(voices.error)}</Notice>
        ) : filtered.length === 0 ? (
          <Notice kind="info" title={`No voices for ${languageName(language)} with these filters`}>
            Try "All" sources. Local voices exist only for languages their engine supports; we never claim support that isn't there.
          </Notice>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
            {filtered.slice(0, 120).map((v: Voice) => (
              <VoiceCard
                key={`${v.provider}:${v.id}`}
                voice={v}
                selected={v.provider === n.provider && v.id === n.voice_id}
                previewState={preview.stateOf(v.provider, v.id)}
                onPreview={() => void preview.toggle(v)}
                onSelect={() => update.mutate({ provider: v.provider, voice_id: v.id })}
                onInstall={() => install.mutate(v.id)}
                installing={(install.isPending && install.variables === v.id) || installJob?.voice === v.id}
              />
            ))}
          </div>
        )}
        {installing && installJob && (
          <Notice kind="info" title={`Installing ${installJob.voice}`}>
            {installing.message} {installing.progress ? `${Math.round(installing.progress)}%` : ""}
          </Notice>
        )}
      </div>

      <aside className="space-y-5 xl:sticky xl:top-6 xl:self-start">
        <div className="surface space-y-4 p-5">
          <h2 className="font-display text-xl font-semibold text-paper-50">Turn this book into an audiobook</h2>
          {estimate.data ? (
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <dt className="text-xs text-paper-500">Characters</dt>
                <dd className="text-paper-100 tabular-nums">{formatNumber(estimate.data.characters)}</dd>
              </div>
              <div>
                <dt className="text-xs text-paper-500">Estimated length</dt>
                <dd className="text-paper-100 tabular-nums">~{Math.round(estimate.data.estimated_audio_minutes)} min</dd>
              </div>
              {estimate.data.cost && (
                <div className="col-span-2">
                  <dt className="text-xs text-paper-500">Estimated cost</dt>
                  <dd className="text-paper-100">
                    {estimate.data.cost.currency === "USD" ? "$" : ""}
                    {estimate.data.cost.amount.toFixed(2)} {estimate.data.cost.currency !== "USD" ? estimate.data.cost.currency : ""}
                    {estimate.data.cost.basis && <span className="block text-[11px] text-paper-500">{estimate.data.cost.basis}</span>}
                  </dd>
                </div>
              )}
            </dl>
          ) : (
            <Skeleton className="h-12" />
          )}
          {providerInfo && (
            <p className="flex gap-2 text-xs leading-relaxed text-paper-400">
              {providerInfo.is_local ? <HardDrive className="mt-0.5 size-3.5 shrink-0 text-sage-400" /> : <Cloud className="mt-0.5 size-3.5 shrink-0 text-sky-400" />}
              {providerInfo.privacy_note}
            </p>
          )}
          <Button
            variant="primary"
            size="lg"
            className="w-full"
            icon={<Sparkles className="size-4" />}
            disabled={!n.voice_id || book.status === "analyzing" || book.status === "generating"}
            loading={generate.isPending}
            onClick={() => (cloud && prefs.data?.confirm_cloud_processing !== false ? setConfirm(true) : generate.mutate(false))}
          >
            {book.status === "generating" ? "Creating…" : hasAudio ? "Update Audiobook" : "Create Audiobook"}
          </Button>
          {hasAudio && <p className="text-[11px] text-paper-500">Only chapters whose text or voice settings changed are regenerated; everything else is reused.</p>}
        </div>

        {otherLangs.length > 0 && (
          <div className="surface space-y-3 p-5">
            <h3 className="flex items-center gap-2 text-sm font-medium text-paper-100">
              <Languages className="size-4 text-orchid-400" /> Mixed-language book
            </h3>
            <p className="text-xs text-paper-400">Paragraphs in these languages use their own voice.</p>
            {otherLangs.map((lang) => {
              const options = all.filter((v) => v.installed && (v.language === lang || v.language === "mul"));
              const cur = n.language_voices[lang];
              return (
                <div key={lang} className="space-y-1">
                  <label htmlFor={`lv-${lang}`} className="text-xs text-paper-300">
                    {languageName(lang)}
                  </label>
                  <Select
                    id={`lv-${lang}`}
                    value={cur?.voice_id ? `${cur.provider}|${cur.voice_id}` : ""}
                    onChange={(e) => {
                      const [p, ...id] = e.target.value.split("|");
                      const next = { ...n.language_voices };
                      if (!e.target.value) delete next[lang];
                      else next[lang] = { provider: p, voice_id: id.join("|") };
                      update.mutate({ language_voices: next });
                    }}
                  >
                    <option value="">Automatic{options.length ? "" : " (no voice available)"}</option>
                    {options.map((v) => (
                      <option key={`${v.provider}|${v.id}`} value={`${v.provider}|${v.id}`}>
                        {v.name} · {v.provider_name}
                      </option>
                    ))}
                  </Select>
                </div>
              );
            })}
          </div>
        )}

        <details className="surface group p-5" open>
          <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-medium text-paper-100">
            <span className="flex items-center gap-2">
              <SlidersHorizontal className="size-4 text-paper-400" /> Advanced settings
            </span>
            <Badge>{n.format.toUpperCase()} · {n.bitrate}</Badge>
          </summary>
          <div className="mt-6">
            <NarrationSettings n={n} provider={providerInfo} onChange={(patch) => update.mutate(patch)} />
          </div>
        </details>
      </aside>

      <Dialog
        open={confirm}
        onClose={() => setConfirm(false)}
        title="Send this book to a cloud service?"
        description={providerInfo?.privacy_note}
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirm(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                setConfirm(false);
                generate.mutate(false);
              }}
            >
              Yes, generate
            </Button>
          </>
        }
      >
        <p className="text-sm text-paper-300">
          {providerInfo?.display_name} runs outside this machine. About {formatNumber(estimate.data?.characters)} characters of your book's text will be sent. Choose a local voice to keep everything on
          this computer.
        </p>
      </Dialog>
    </div>
  );
}
