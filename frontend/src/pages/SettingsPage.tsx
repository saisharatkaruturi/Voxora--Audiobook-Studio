import { useEffect, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cloud, HardDrive, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Badge, Notice, PageLoader } from "@/components/ui/Feedback";
import { Field, Input, Segmented, Select, Toggle } from "@/components/ui/Form";
import { toast } from "@/components/ui/Toast";
import { authApi, systemApi, voicesApi } from "@/services/api";
import { errorMessage } from "@/services/http";
import { authConfig, supabase, supabaseError } from "@/services/supabase";
import { qk } from "@/services/queryClient";
import { useAuth } from "@/stores/auth";
import { ThemePicker } from "@/components/ui/ThemeToggle";
import type { Preferences } from "@/types/api";
import { formatBytes } from "@/utils/format";
import { languageName } from "@/utils/languages";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";

const SPEEDS = [0.75, 1, 1.1, 1.25, 1.5, 1.75, 2];

function Section({ id, title, description, children }: { id?: string; title: string; description?: string; children: ReactNode }) {
  return (
    <section id={id} className="surface scroll-mt-6 p-6" aria-labelledby={`${id ?? title}-h`}>
      <h2 id={`${id ?? title}-h`} className="font-display text-xl text-paper-50">
        {title}
      </h2>
      {description && <p className="mt-1 text-sm text-paper-400">{description}</p>}
      <div className="mt-6">{children}</div>
    </section>
  );
}

export default function SettingsPage() {
  const qc = useQueryClient();
  const prefs = useQuery({ queryKey: qk.prefs, queryFn: systemApi.preferences });
  const status = useQuery({ queryKey: qk.status, queryFn: systemApi.status });
  const storage = useQuery({ queryKey: ["storage"], queryFn: systemApi.storage });
  const voices = useQuery({ queryKey: qk.voices({ installed: true }), queryFn: () => voicesApi.list({}), staleTime: 60_000 });
  useDocumentTitle("Settings");
  const [voiceLang, setVoiceLang] = useState("en");

  useEffect(() => {
    if (window.location.hash) document.querySelector(window.location.hash)?.scrollIntoView();
  }, [status.data]);

  const save = useMutation({
    mutationFn: (patch: Partial<Preferences>) => systemApi.savePreferences(patch),
    onMutate: (patch) => {
      const prev = qc.getQueryData<Preferences>(qk.prefs);
      if (prev) qc.setQueryData(qk.prefs, { ...prev, ...patch });
      return { prev };
    },
    onSuccess: (p) => qc.setQueryData(qk.prefs, p),
    onError: (e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(qk.prefs, ctx.prev);
      toast.error(errorMessage(e));
    },
  });

  if (prefs.isPending || status.isPending) return <PageLoader label="Opening settings" />;
  if (prefs.isError) return <Notice kind="error">{errorMessage(prefs.error)}</Notice>;
  const p = prefs.data;
  const s = status.data;
  const langVoices = (voices.data?.items ?? []).filter((v) => v.installed && (v.language === voiceLang || v.language === "mul"));
  const currentDefault = p.default_voices[voiceLang];

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header>
        <h1 className="font-display text-4xl font-semibold tracking-tight text-paper-50">Settings</h1>
      </header>

      <Section title="Appearance" description="Choose how VOXORA looks on this device.">
        <ThemePicker />
      </Section>

      <Profile />

      <Section title="Narration defaults" description="Applied to books you add from now on. Each book can still be changed in Voice Studio.">
        <div className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-[180px_1fr]">
            <Field label="Language" htmlFor="dv-lang">
              <Select id="dv-lang" value={voiceLang} onChange={(e) => setVoiceLang(e.target.value)}>
                {(s?.languages ?? []).map((l) => (
                  <option key={l.code} value={l.code}>
                    {languageName(l.code, l.name)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={`Default ${languageName(voiceLang)} narrator`} htmlFor="dv-voice" hint={langVoices.length ? undefined : "No installed voice supports this language."}>
              <Select
                id="dv-voice"
                value={currentDefault ? `${currentDefault.provider}|${currentDefault.voice_id}` : ""}
                onChange={(e) => {
                  const next = { ...p.default_voices };
                  if (!e.target.value) delete next[voiceLang];
                  else {
                    const [provider, ...rest] = e.target.value.split("|");
                    next[voiceLang] = { provider, voice_id: rest.join("|") };
                  }
                  save.mutate({ default_voices: next });
                }}
              >
                <option value="">Server default</option>
                {langVoices.map((v) => (
                  <option key={`${v.provider}|${v.id}`} value={`${v.provider}|${v.id}`}>
                    {v.name} · {v.provider_name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <div>
            <p className="mb-2 text-[13px] font-medium text-paper-300">Narration speed</p>
            <Segmented<number> label="Default narration speed" value={p.default_speed} onChange={(v) => save.mutate({ default_speed: v })} options={SPEEDS.map((v) => ({ value: v, label: `${v}×` }))} />
          </div>
          <Toggle checked={p.narration_cleanup} onChange={(v) => save.mutate({ narration_cleanup: v })} label="Narration Cleanup on by default" description="Reads numbers, abbreviations and symbols naturally without changing the text." />
          <Toggle checked={p.build_full_audiobook} onChange={(v) => save.mutate({ build_full_audiobook: v })} label="Build a single full-book file" />
          <div className="grid grid-cols-2 gap-4">
            <Field label="Audio format" htmlFor="pf-fmt">
              <Select id="pf-fmt" value={p.audio_format ?? ""} onChange={(e) => save.mutate({ audio_format: e.target.value || null })}>
                <option value="">Server default (MP3)</option>
                <option value="mp3">MP3</option>
                <option value="m4a">M4A (AAC)</option>
                <option value="wav">WAV</option>
              </Select>
            </Field>
            <Field label="Bitrate" htmlFor="pf-br">
              <Select id="pf-br" value={p.audio_bitrate ?? ""} onChange={(e) => save.mutate({ audio_bitrate: e.target.value || null })}>
                <option value="">Server default</option>
                {["48k", "64k", "96k", "128k", "160k", "192k"].map((b) => (
                  <option key={b} value={b}>
                    {b.replace("k", " kbps")}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
        </div>
      </Section>

      <Section title="Listening">
        <div className="space-y-5">
          <div>
            <p className="mb-2 text-[13px] font-medium text-paper-300">Default playback speed for new books</p>
            <Segmented<number> label="Default playback speed" value={p.playback_rate} onChange={(v) => save.mutate({ playback_rate: v })} options={SPEEDS.map((v) => ({ value: v, label: `${v}×` }))} />
          </div>
          <Toggle
            checked={p.confirm_cloud_processing}
            onChange={(v) => save.mutate({ confirm_cloud_processing: v })}
            label="Ask before sending a book to a cloud voice"
            description="Shows a confirmation before any text leaves this machine."
          />
        </div>
      </Section>

      {s && (
        <Section id="privacy" title="Privacy" description="Where your books are processed and how long files are kept.">
          <ul className="divide-y divide-white/[0.05]">
            <EngineRow label="Storage" local={s.storage.local} detail={s.storage.local ? `On this server · ${formatBytes(s.storage.free_bytes)} free` : `${s.storage.provider} (cloud storage)`} available />
            <EngineRow
              label="Text recognition (OCR)"
              local
              available={s.ocr.some((o) => o.available)}
              detail={s.ocr.filter((o) => o.available).map((o) => o.name).join(", ") || "No OCR engine installed"}
            />
            {s.tts.map((t) => (
              <EngineRow key={t.name} label={t.display_name} local={t.is_local} available={t.available} detail={t.available ? t.privacy_note : t.reason ?? "Unavailable"} badge={t.name === s.default_tts ? "Default" : undefined} />
            ))}
            <EngineRow label={`AI model${s.llm.model ? ` · ${s.llm.model}` : ""}`} local={s.llm.is_local} available={s.llm.available} detail={s.llm.available ? s.llm.privacy_note || (s.llm.is_local ? "Runs on this machine." : "Passages are sent to the provider.") : s.llm.reason ?? "Not configured"} />
            <EngineRow label="Search embeddings" local={s.embeddings.is_local} available detail={s.embeddings.model} />
          </ul>
          <div className="mt-6 space-y-2 text-sm text-paper-400">
            <p className="flex gap-2">
              <ShieldCheck className="mt-0.5 size-4 shrink-0 text-sage-400" /> {s.privacy.retention} Temporary processing files are removed after {s.privacy.temp_file_ttl_hours} hours.
            </p>
            <p className="flex gap-2">
              <ShieldCheck className="mt-0.5 size-4 shrink-0 text-sage-400" /> {s.privacy.analytics ? "Anonymous usage analytics are enabled on this server." : "No analytics or telemetry are collected."}
            </p>
            <p className="flex gap-2">
              <ShieldCheck className="mt-0.5 size-4 shrink-0 text-sage-400" /> Delete a book, its audio or its original file at any time from the book's page.
            </p>
          </div>
        </Section>
      )}

      <StorageSection used={storage.data} />
    </div>
  );
}

function EngineRow({ label, local, available, detail, badge }: { label: string; local: boolean; available: boolean; detail: string; badge?: string }) {
  return (
    <li className="flex items-start gap-3 py-3">
      {local ? <HardDrive className="mt-0.5 size-4 shrink-0 text-sage-400" aria-label="Local" /> : <Cloud className="mt-0.5 size-4 shrink-0 text-sky-400" aria-label="Cloud" />}
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-2 text-sm text-paper-100">
          {label}
          {badge && <Badge tone="amber">{badge}</Badge>}
          {!available && <Badge>Not set up</Badge>}
        </p>
        <p className="mt-0.5 text-xs text-paper-500">{detail}</p>
      </div>
      <span className="text-xs text-paper-500">{local ? "Local" : "Cloud"}</span>
    </li>
  );
}

function Profile() {
  const { user, setUser } = useAuth();
  const [name, setName] = useState(user?.display_name ?? "");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const config = useQuery({ queryKey: ["auth-config"], queryFn: authConfig, staleTime: Infinity });
  const viaSupabase = config.data?.provider === "supabase";
  const save = useMutation({
    mutationFn: async () => {
      if (viaSupabase && next) {
        const client = await supabase();
        if (!client) throw new Error("Sign-in isn't configured on this server.");
        const { error } = await client.auth.updateUser({ password: next });
        if (error) throw new Error(supabaseError(error));
        return authApi.updateMe({ display_name: name.trim() || undefined });
      }
      return authApi.updateMe({ display_name: name.trim() || undefined, ...(next ? { current_password: current, new_password: next } : {}) });
    },
    onSuccess: (u) => {
      setUser(u);
      setCurrent("");
      setNext("");
      toast.success("Profile saved.");
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Section id="profile" title="Profile">
      <form
        className="grid gap-4 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <Field label="Display name" htmlFor="pf-name">
          <Input id="pf-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
        </Field>
        <Field label="Email" htmlFor="pf-email">
          <Input id="pf-email" value={user?.email ?? ""} disabled />
        </Field>
        {!viaSupabase && (
          <Field label="Current password" htmlFor="pf-cur">
            <Input id="pf-cur" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />
          </Field>
        )}
        <Field label="New password" htmlFor="pf-new" hint="Leave empty to keep your password.">
          <Input id="pf-new" type="password" autoComplete="new-password" minLength={8} value={next} onChange={(e) => setNext(e.target.value)} />
        </Field>
        <div className="sm:col-span-2">
          <Button type="submit" loading={save.isPending} disabled={!name.trim() || (!!next && next.length < 8)}>
            Save profile
          </Button>
        </div>
      </form>
    </Section>
  );
}

function StorageSection({ used }: { used?: { books: number; audio_bytes: number; tts_cache_bytes: number } }) {
  const isAdmin = useAuth((s) => s.user?.is_admin);
  const qc = useQueryClient();
  const clear = useMutation({
    mutationFn: systemApi.clearCache,
    onSuccess: () => {
      toast.success("Voice cache cleared.");
      void qc.invalidateQueries({ queryKey: ["storage"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Section title="Storage">
      <dl className="grid grid-cols-3 gap-4">
        <div>
          <dt className="text-xs text-paper-500">Books</dt>
          <dd className="text-lg text-paper-100 tabular-nums">{used?.books ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-xs text-paper-500">Your audio</dt>
          <dd className="text-lg text-paper-100 tabular-nums">{formatBytes(used?.audio_bytes)}</dd>
        </div>
        <div>
          <dt className="text-xs text-paper-500">Voice cache</dt>
          <dd className="text-lg text-paper-100 tabular-nums">{formatBytes(used?.tts_cache_bytes)}</dd>
        </div>
      </dl>
      <p className="mt-4 text-xs text-paper-500">The voice cache stores synthesized sentences so unchanged text is never generated twice. Clearing it is safe; audio is re-synthesized when needed.</p>
      {isAdmin && (
        <Button className="mt-4" size="sm" variant="danger" onClick={() => clear.mutate()} loading={clear.isPending}>
          Clear voice cache
        </Button>
      )}
    </Section>
  );
}
