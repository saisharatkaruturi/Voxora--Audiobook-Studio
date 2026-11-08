import { request } from "@/services/http";
import type {
  Book,
  Bookmark,
  CastMember,
  Chapter,
  ChapterDetail,
  ChatMessage,
  DialogueLine,
  DownloadItem,
  Estimate,
  Insights,
  Job,
  Narration,
  Playback,
  Preferences,
  Progress,
  SystemStatus,
  Timings,
  TTSProviderInfo,
  User,
  Voice,
  BookFinderResult,
} from "@/types/api";

type Items<T> = { items: T[] };

export interface AuthConfig {
  /** "supabase": sign in through Supabase Auth; "local": VOXORA's built-in accounts. */
  provider: "local" | "supabase";
  supabase_url?: string | null;
  supabase_anon_key?: string | null;
  /** Social sign-in providers enabled in Supabase, e.g. ["google"]. */
  oauth_providers?: string[];
  /** "device": finished audio is stored in the listener's browser, not on the server. */
  audio_delivery?: "server" | "device";
  registration_open: boolean;
  has_users: boolean;
}

export const authApi = {
  config: () => request<AuthConfig>("/api/auth/config"),
  login: (email: string, password: string) =>
    request<{ token: string; user: User }>("/api/auth/login", { body: { email, password } }),
  register: (email: string, password: string, display_name: string) =>
    request<{ token: string; user: User }>("/api/auth/register", { body: { email, password, display_name } }),
  me: () => request<User>("/api/auth/me"),
  updateMe: (body: { display_name?: string; current_password?: string; new_password?: string }) =>
    request<User>("/api/auth/me", { method: "PATCH", body }),
};

export interface LibraryQuery {
  q?: string;
  status?: string;
  sort?: string;
  limit?: number;
  offset?: number;
}

export type BookPatch = Partial<Pick<Book, "title" | "subtitle" | "author" | "narrator" | "description" | "genre" | "year" | "language">> & {
  narration?: Partial<Narration>;
};

export const booksApi = {
  list: (q: LibraryQuery) => request<{ items: Book[]; total: number }>("/api/books", { query: { ...q } }),
  continueListening: () => request<Items<Book>>("/api/books/continue"),
  get: (id: string) => request<Book>(`/api/books/${id}`),
  refreshInfo: (id: string) => request<Job>(`/api/books/${id}/info`, { method: "POST" }),
  upload: (file: File, opts: { autoAnalyze?: boolean; language?: string; ocrMode?: string } = {}) => {
    const form = new FormData();
    form.append("file", file);
    form.append("auto_analyze", String(opts.autoAnalyze ?? true));
    form.append("language", opts.language ?? "auto");
    form.append("ocr_mode", opts.ocrMode ?? "auto");
    return request<{ book: Book; job: Job | null }>("/api/books", { body: form });
  },
  update: (id: string, body: BookPatch) => request<Book>(`/api/books/${id}`, { method: "PATCH", body }),
  remove: (id: string) => request<void>(`/api/books/${id}`, { method: "DELETE" }),
  removeAudio: (id: string) => request<{ removed_files: number }>(`/api/books/${id}/audio`, { method: "DELETE" }),
  removeOriginal: (id: string) => request<{ removed: boolean }>(`/api/books/${id}/original`, { method: "DELETE" }),
  analyze: (id: string, body: { ocr_mode?: string; languages?: string[] } = {}) =>
    request<Job>(`/api/books/${id}/analyze`, { body: { ocr_mode: "auto", languages: [], ...body } }),
  uploadCover: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Book>(`/api/books/${id}/cover`, { body: form });
  },
  contentMode: (id: string, mode: "narrative" | "full" | "custom") =>
    request<{ mode: string; items: Chapter[] }>(`/api/books/${id}/content-mode`, { body: { mode } }),
  buildM4b: (id: string) => request<Job>(`/api/books/${id}/export/m4b`, { method: "POST" }),
  generateCover: (id: string) => request<Book>(`/api/books/${id}/cover/generate`, { method: "POST" }),
  estimate: (id: string) => request<Estimate>(`/api/books/${id}/estimate`),
  generate: (id: string, body: { chapter_ids?: string[] | null; force?: boolean } = {}) =>
    request<Job>(`/api/books/${id}/generate`, { body: { chapter_ids: null, force: false, ...body } }),
  downloads: (id: string) => request<Items<DownloadItem>>(`/api/books/${id}/downloads`),
};

export const chaptersApi = {
  list: (bookId: string) => request<Items<Chapter>>(`/api/books/${bookId}/chapters`),
  get: (id: string) => request<ChapterDetail>(`/api/chapters/${id}`),
  create: (bookId: string, body: { title: string; text: string; after_position?: number | null }) =>
    request<Chapter>(`/api/books/${bookId}/chapters`, { body }),
  update: (id: string, body: { title?: string; kind?: string; include_in_audio?: boolean; text?: string }) =>
    request<ChapterDetail>(`/api/chapters/${id}`, { method: "PATCH", body }),
  remove: (id: string) => request<void>(`/api/chapters/${id}`, { method: "DELETE" }),
  reorder: (bookId: string, chapter_ids: string[]) =>
    request<Items<Chapter>>(`/api/books/${bookId}/chapters/reorder`, { body: { chapter_ids } }),
  merge: (bookId: string, chapter_ids: string[]) =>
    request<{ chapter_id: string }>(`/api/books/${bookId}/chapters/merge`, { body: { chapter_ids } }),
  split: (id: string, paragraph_index: number, title?: string) =>
    request<{ chapter_id: string }>(`/api/chapters/${id}/split`, { body: { paragraph_index, title } }),
  generate: (id: string) => request<Job>(`/api/chapters/${id}/generate`, { method: "POST" }),
  timings: (id: string) => request<Timings>(`/api/chapters/${id}/timings`),
  narrationPreview: (id: string) =>
    request<{ chunks: { paragraph: number; voice: string; provider: string; speaker: string | null; text: string }[]; warnings: string[]; characters: number }>(
      `/api/chapters/${id}/narration-preview`,
    ),
  dialogue: (id: string) => request<Items<DialogueLine>>(`/api/chapters/${id}/dialogue`),
};

export const jobsApi = {
  list: (q: { book_id?: string; active?: boolean; limit?: number } = {}) => request<Items<Job>>("/api/jobs", { query: { ...q } }),
  get: (id: string) => request<Job>(`/api/jobs/${id}`),
  pause: (id: string) => request<Job>(`/api/jobs/${id}/pause`, { method: "POST" }),
  resume: (id: string) => request<Job>(`/api/jobs/${id}/resume`, { method: "POST" }),
  retry: (id: string) => request<Job>(`/api/jobs/${id}/retry`, { method: "POST" }),
  cancel: (id: string) => request<Job>(`/api/jobs/${id}/cancel`, { method: "POST" }),
};

export const playerApi = {
  playback: (bookId: string) => request<Playback>(`/api/books/${bookId}/playback`),
  audioReceived: (bookId: string, chapterId: string, audio_hash: string) =>
    request<{ on_device: boolean }>(`/api/books/${bookId}/chapters/${chapterId}/audio/received`, { body: { audio_hash } }),
  saveProgress: (
    bookId: string,
    body: { chapter_id: string | null; position_seconds: number; playback_rate: number; completed?: boolean },
    keepalive = false,
  ) => request<Progress>(`/api/books/${bookId}/progress`, { method: "PUT", body, keepalive }),
  bookmarks: (bookId: string) => request<Items<Bookmark>>(`/api/books/${bookId}/bookmarks`),
  addBookmark: (bookId: string, body: { chapter_id: string | null; position_seconds: number; note?: string | null }) =>
    request<Bookmark>(`/api/books/${bookId}/bookmarks`, { body }),
  updateBookmark: (id: string, note: string | null) => request<Bookmark>(`/api/bookmarks/${id}`, { method: "PATCH", body: { note } }),
  removeBookmark: (id: string) => request<void>(`/api/bookmarks/${id}`, { method: "DELETE" }),
};

export const voicesApi = {
  providers: () => request<Items<TTSProviderInfo>>("/api/tts/providers"),
  list: (q: { provider?: string; language?: string; include_catalog?: boolean } = {}) =>
    request<{ items: Voice[]; languages: { code: string; name: string }[] }>("/api/voices", { query: { ...q } }),
  preview: (body: { provider: string; voice_id: string; speed?: number; pitch?: number; text?: string; language?: string | null; book_id?: string }) =>
    request<{ url: string }>("/api/voices/preview", { body }),
  installPiper: (voice: string) => request<Job>("/api/voices/piper/install", { body: { voice } }),
};

export const aiApi = {
  cast: (bookId: string) => request<{ items: CastMember[]; enabled: boolean; sample: DialogueLine[] }>(`/api/books/${bookId}/cast`),
  analyzeCast: (bookId: string, use_llm: boolean) => request<Job>(`/api/books/${bookId}/cast/analyze`, { body: { use_llm } }),
  updateCast: (id: string, body: { provider?: string | null; voice_id?: string | null; gender_hint?: string | null }) =>
    request<CastMember>(`/api/cast/${id}`, { method: "PATCH", body }),
  askStatus: (bookId: string) =>
    request<{ indexed_chunks: number; index_job: Job | null; llm: SystemStatus["llm"]; embeddings: string }>(`/api/books/${bookId}/ask/status`),
  index: (bookId: string) => request<Job>(`/api/books/${bookId}/index`, { method: "POST" }),
  ask: (bookId: string, question: string, spoiler_safe: boolean) =>
    request<{ job: Job }>(`/api/books/${bookId}/ask`, { body: { question, spoiler_safe } }),
  chat: (bookId: string) => request<Items<ChatMessage>>(`/api/books/${bookId}/chat`),
  clearChat: (bookId: string) => request<void>(`/api/books/${bookId}/chat`, { method: "DELETE" }),
  insights: (bookId: string) => request<Insights>(`/api/books/${bookId}/insights`),
  createInsights: (bookId: string, kinds?: string[]) => request<Job>(`/api/books/${bookId}/insights`, { body: { kinds: kinds ?? null } }),
};

export const systemApi = {
  status: () => request<SystemStatus>("/api/system/status"),
  preferences: () => request<Preferences>("/api/settings"),
  savePreferences: (body: Partial<Preferences>) => request<Preferences>("/api/settings", { method: "PUT", body }),
  storage: () => request<{ books: number; audio_bytes: number; tts_cache_bytes: number }>("/api/storage"),
  clearCache: () => request<Record<string, unknown>>("/api/storage/tts-cache", { method: "DELETE" }),
  search: (q: string) =>
    request<{ books: { id: string; title: string; author: string | null }[]; chapters: { id: string; title: string; book_id: string; book_title: string }[] }>(
      "/api/search",
      { query: { q } },
    ),
  findBooks: (q: string) => request<BookFinderResult>("/api/search/books", { query: { q } }),
};
