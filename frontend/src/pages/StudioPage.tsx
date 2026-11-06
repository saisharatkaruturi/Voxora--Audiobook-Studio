import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { ArrowRight, Cloud, HardDrive, Search, Star, Users } from "lucide-react";
import { BookCover } from "@/components/book/BookCover";
import { VoiceWaveform } from "@/components/audio/AudioWaveform";
import { Badge, Notice, Skeleton } from "@/components/ui/Feedback";
import { Input, Segmented, Select } from "@/components/ui/Form";
import { toast } from "@/components/ui/Toast";
import { reveal, stagger } from "@/config/motion";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { useVoicePreview } from "@/hooks/useVoicePreview";
import { booksApi, systemApi, voicesApi } from "@/services/api";
import { errorMessage } from "@/services/http";
import { qk } from "@/services/queryClient";
import type { Preferences, Voice } from "@/types/api";
import { cn } from "@/utils/format";
import { FEATURED_LANGUAGES, languageName } from "@/utils/languages";

/**
 * Studio: audition every narrator the engines actually provide, set defaults
 * per language, and go cast characters for a specific book.
 */
export default function StudioPage() {
  useDocumentTitle("Studio");
  const qc = useQueryClient();
  const [lang, setLang] = useState("en");
  const [source, setSource] = useState<"all" | "local" | "cloud">("all");
  const [q, setQ] = useState("");
  const voices = useQuery({ queryKey: qk.voices({ installed: true }), queryFn: () => voicesApi.list({}), staleTime: 60_000 });
  const prefs = useQuery({ queryKey: qk.prefs, queryFn: systemApi.preferences });
  const books = useQuery({ queryKey: qk.books({ studio: true }), queryFn: () => booksApi.list({ limit: 12, sort: "recent" }) });
  const preview = useVoicePreview();

  const setDefault = useMutation({
    mutationFn: (v: Voice) => systemApi.savePreferences({ default_voices: { ...(prefs.data?.default_voices ?? {}), [lang]: { provider: v.provider, voice_id: v.id } } }),
    onSuccess: (p: Preferences, v) => {
      qc.setQueryData(qk.prefs, p);
      toast.success(`${v.name} will narrate new ${languageName(lang)} books.`);
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const all = voices.data?.items ?? [];
  const langs = useMemo(() => {
    const codes = new Set(all.map((v) => v.language).filter((l) => l !== "mul"));
    return [...FEATURED_LANGUAGES.filter((l) => codes.has(l)), ...[...codes].filter((l) => !FEATURED_LANGUAGES.includes(l)).sort()];
  }, [all]);
  const filtered = all
    .filter((v) => v.language === lang || v.language === "mul")
    .filter((v) => source === "all" || (source === "local" ? v.is_local : !v.is_local))
    .filter((v) => !q || `${v.name} ${v.accent} ${v.style}`.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => Number(b.is_local) - Number(a.is_local) || a.name.localeCompare(b.name));
  const def = prefs.data?.default_voices?.[lang];

  return (
    <div className="space-y-14">
      <header className="max-w-3xl">
        <p className="eyebrow text-mint-400/90">Studio</p>
        <h1 className="mt-3 font-display text-4xl font-semibold tracking-tight text-paper-50 sm:text-6xl">Give your story a voice.</h1>
        <p className="mt-3 text-paper-400">Audition narrators, then cast every character individually.</p>
      </header>

      <section aria-labelledby="audition" className="space-y-6">
        <div className="flex flex-wrap items-center gap-3">
          <h2 id="audition" className="mr-auto font-display text-2xl font-semibold text-paper-50">
            Narrators
          </h2>
          <div className="w-48">
            <Select aria-label="Language" value={lang} onChange={(e) => setLang(e.target.value)}>
              {langs.map((l) => (
                <option key={l} value={l}>
                  {languageName(l)}
                </option>
              ))}
            </Select>
          </div>
          <Segmented
            label="Voice source"
            value={source}
            onChange={setSource}
            options={[
              { value: "all", label: "All" },
              { value: "local", label: "On this machine" },
              { value: "cloud", label: "Cloud" },
            ]}
          />
          <div className="relative w-56">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-paper-500" />
            <Input className="pl-9" placeholder="Search voices" aria-label="Search voices" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
        </div>

        {voices.isPending ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-44" />
            ))}
          </div>
        ) : voices.isError ? (
          <Notice kind="error">{errorMessage(voices.error)}</Notice>
        ) : filtered.length === 0 ? (
          <Notice kind="info">No {source === "all" ? "" : source + " "}voices for {languageName(lang)}. Engines only list languages they really speak.</Notice>
        ) : (
          <motion.div variants={stagger(0.04)} initial="hidden" animate="show" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {filtered.slice(0, 60).map((v) => {
              const state = preview.stateOf(v.provider, v.id);
              const isDefault = def?.provider === v.provider && def?.voice_id === v.id;
              return (
                <motion.div
                  key={`${v.provider}:${v.id}`}
                  variants={reveal}
                  className={cn(
                    "group surface relative overflow-hidden p-5 transition-all duration-300 hover:-translate-y-1 hover:border-white/[0.16]",
                    state === "playing" && "border-orchid-400/40 shadow-[var(--shadow-glow)]",
                  )}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="flex items-center gap-2 font-display text-xl font-semibold text-paper-50">
                        {v.name}
                        {isDefault && <Star className="size-4 fill-amber-400 text-amber-400" aria-label="Your default" />}
                      </p>
                      <p className="truncate text-sm text-paper-400 transition-colors group-hover:text-paper-200">{v.accent ?? languageName(v.language, v.language_name)}</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => void preview.toggle(v)}
                      aria-label={state === "playing" ? `Stop ${v.name}` : `Audition ${v.name}${v.quality ? ` (${v.quality})` : ""}`}
                      className={cn("neo flex size-12 shrink-0 items-center justify-center rounded-full transition-colors", state === "playing" ? "text-mint-400" : "text-paper-100")}
                    >
                      {state === "loading" ? <span className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" /> : state === "playing" ? <span className="size-3 rounded-sm bg-current" /> : <span className="ml-0.5 size-0 border-y-[7px] border-l-[11px] border-y-transparent border-l-current" />}
                    </button>
                  </div>
                  <VoiceWaveform active={state === "playing"} className="mt-5 opacity-80 transition-opacity group-hover:opacity-100" />
                  <div className="mt-4 flex flex-wrap items-center gap-1.5">
                    <Badge icon={v.is_local ? <HardDrive className="size-3" /> : <Cloud className="size-3" />} tone={v.is_local ? "sage" : "sky"}>
                      {v.is_local ? "Local" : "Cloud"}
                    </Badge>
                    {v.gender && <Badge>{v.gender[0].toUpperCase() + v.gender.slice(1)}</Badge>}
                    {v.style && <Badge className="max-w-40 truncate">{v.style}</Badge>}
                    {v.quality && <Badge>{v.quality}</Badge>}
                    <button
                      type="button"
                      onClick={() => setDefault.mutate(v)}
                      disabled={isDefault}
                      className="ml-auto text-xs text-paper-400 hover:text-orchid-300 disabled:text-amber-300"
                    >
                      {isDefault ? "Default narrator" : "Make default"}
                    </button>
                  </div>
                </motion.div>
              );
            })}
          </motion.div>
        )}
      </section>

      <motion.section variants={reveal} initial="hidden" whileInView="show" viewport={{ once: true, margin: "-60px" }} aria-labelledby="cast">
        <div className="mb-6 flex items-end justify-between gap-4">
          <div>
            <h2 id="cast" className="font-display text-2xl font-semibold text-paper-50">
              Cast a book
            </h2>
            <p className="mt-1 text-sm text-paper-400">Find the characters in a story and give each one a voice.</p>
          </div>
        </div>
        {books.data?.items.length ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {books.data.items
              .filter((b) => b.status !== "uploaded" && b.status !== "analyzing")
              .map((b) => (
                <Link key={b.id} to={`/books/${b.id}/cast`} className="surface group flex items-center gap-4 p-3 pr-5 transition-all hover:-translate-y-0.5 hover:border-white/[0.16]">
                  <BookCover url={b.cover_url} title={b.title} size="sm" className="w-12 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-paper-50">{b.title}</p>
                    <p className="flex items-center gap-1.5 text-xs text-paper-500">
                      <Users className="size-3" /> {b.narration?.cast_mode ? "Full cast on" : "Single narrator"}
                    </p>
                  </div>
                  <ArrowRight className="size-4 text-paper-500 transition-transform group-hover:translate-x-1 group-hover:text-paper-100" />
                </Link>
              ))}
          </div>
        ) : (
          <p className="text-sm text-paper-500">
            Add a book first. <Link to="/create" className="text-orchid-300 hover:underline">Bring one into VOXORA</Link>.
          </p>
        )}
      </motion.section>
    </div>
  );
}
