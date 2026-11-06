// Types mirror the backend serializers in backend/app/schemas/common.py.

export interface ApiErrorBody {
  code: string;
  message: string;
  retryable: boolean;
  details: Record<string, unknown>;
}

export interface User {
  id: string;
  email: string;
  display_name: string;
  is_admin: boolean;
  created_at: string;
}

export type BookStatus = "uploaded" | "analyzing" | "review" | "generating" | "ready" | "failed";
export type JobStatus = "queued" | "running" | "paused" | "completed" | "failed" | "cancelled";
export type ChapterAudioStatus = "pending" | "queued" | "generating" | "done" | "failed" | "skipped";

export interface JobStage {
  key: string;
  label: string;
  status: "pending" | "active" | "done" | "failed" | "skipped" | string;
}

export interface Job {
  id: string;
  type: string;
  status: JobStatus;
  book_id: string | null;
  chapter_id: string | null;
  progress: number;
  stage: string | null;
  message: string | null;
  current_chapter: number | null;
  total_chapters: number | null;
  stages: JobStage[];
  result: Record<string, unknown> | null;
  error: ApiErrorBody | null;
  attempts: number;
  max_attempts: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  run_after: string | null;
}

export interface Progress {
  chapter_id: string | null;
  chapter_position: number;
  position_seconds: number;
  book_position_seconds: number;
  playback_rate: number;
  completed: boolean;
  updated_at: string;
}

export interface Narration {
  provider: string;
  voice_id: string | null;
  language_voices: Record<string, { provider?: string; voice_id?: string }>;
  speed: number;
  pitch: number;
  volume: number;
  sentence_pause_ms: number;
  paragraph_pause_ms: number;
  heading_pause_ms: number;
  chapter_pause_ms: number;
  narration_cleanup: boolean;
  ai_ocr_repair: boolean;
  cast_mode: boolean;
  announce_chapter_titles: boolean;
  format: "mp3" | "m4a" | "wav";
  bitrate: string;
  normalize: boolean;
  compress: boolean;
  shorten_long_pauses: boolean;
  build_full_audiobook: boolean;
  content_mode: ContentMode;
}

export type ContentMode = "narrative" | "full" | "custom";

export interface BookWarning {
  code?: string;
  message: string;
  [k: string]: unknown;
}

export interface Book {
  id: string;
  title: string;
  subtitle: string | null;
  author: string | null;
  narrator: string | null;
  description: string | null;
  genre: string | null;
  genres: string[];
  series: string | null;
  series_index: number | null;
  year: string | null;
  language: string | null;
  languages: string[];
  status: BookStatus;
  source_format: string;
  page_count: number | null;
  word_count: number;
  char_count: number;
  ocr_used: boolean;
  ocr_engine: string | null;
  ocr_confidence: number | null;
  warnings: (BookWarning | string)[];
  cover_url: string | null;
  cover_source: string | null;
  narration: Narration;
  total_duration: number | null;
  error: (ApiErrorBody & { stage?: string }) | null;
  chapter_count: number | null;
  chapters_with_audio: number | null;
  narrated_chapters: number | null;
  progress: Progress | null;
  active_job: Job | null;
  created_at: string;
  updated_at: string;
  current_chapter?: { id: string; title: string; duration: number | null } | null;
}

export interface ChapterAudio {
  url: string;
  duration: number;
  format: string;
  size: number;
  timing_source: string | null;
}

export interface Chapter {
  id: string;
  book_id: string;
  position: number;
  title: string;
  kind: string;
  include_in_audio: boolean;
  word_count: number;
  char_count: number;
  language: string | null;
  audio_status: ChapterAudioStatus;
  audio_progress: number;
  audio_error: ApiErrorBody | null;
  duration: number | null;
  stale: boolean;
  detection: { method?: string; confidence?: number; skipped?: "toc_leftover" | "too_short"; [k: string]: unknown };
  group: "front" | "narrative" | "back";
  pages: [number, number] | null;
  text_version: number;
  audio: ChapterAudio | null;
}

export interface Paragraph {
  id: string;
  position: number;
  text: string;
  kind: "text" | "heading";
  language: string | null;
  page: number | null;
  spans: { start: number; end: number; speaker: string | null }[] | null;
}

export interface ChapterDetail extends Chapter {
  paragraphs: Paragraph[];
}

export interface Track {
  chapter_id: string;
  position: number;
  title: string;
  kind: string;
  /** Null once the audio was handed to the listener's device (device delivery). */
  url: string | null;
  duration: number;
  offset: number;
  timing_source: string | null;
  /** Content hash of this chapter's audio; the device files it under this. */
  audio_hash?: string | null;
  /** Id of this audio file; changes whenever the chapter is narrated again. */
  audio_id?: string | null;
  format?: string;
  /** The server gave this audio to a device and no longer has it. */
  on_device?: boolean;
}

export interface Bookmark {
  id: string;
  book_id: string;
  chapter_id: string | null;
  chapter_title: string | null;
  position_seconds: number;
  note: string | null;
  created_at: string;
}

export interface Playback {
  book: { id: string; title: string; author: string | null; narrator: string | null; cover_url: string | null; language: string | null };
  tracks: Track[];
  total_duration: number;
  progress: Progress | null;
  bookmarks: Bookmark[];
  audio_delivery?: "server" | "device";
}

/** [paragraph_position, char_start, char_end, t0, t1] */
export type SentenceTiming = [number, number, number, number, number];

export interface Timings {
  chapter_id: string;
  timing_source: string | null;
  sentences: SentenceTiming[];
  paragraphs: { position: number; text: string; kind: string }[];
}

export interface Voice {
  provider: string;
  id: string;
  name: string;
  language: string;
  language_name: string;
  locale: string | null;
  accent: string | null;
  gender: string | null;
  style: string | null;
  quality: string | null;
  installed: boolean;
  description: string | null;
  languages: string[];
  meta: Record<string, unknown>;
  is_local: boolean;
  provider_name: string;
}

export interface TTSProviderInfo {
  name: string;
  display_name: string;
  available: boolean;
  reason: string | null;
  is_local: boolean;
  supports_pitch: boolean;
  supports_timestamps: boolean;
  requires_api_key: boolean;
  privacy_note: string;
}

export interface Estimate {
  characters: number;
  estimated_audio_minutes: number;
  provider: string;
  is_local: boolean;
  cost: { amount: number; currency: string; basis?: string; [k: string]: unknown } | null;
  privacy_note: string;
}

export interface CastMember {
  id: string;
  name: string;
  role: "narrator" | "character" | "unknown";
  gender_hint: string | null;
  line_count: number;
  provider: string | null;
  voice_id: string | null;
  auto_assigned: boolean;
}

export interface DialogueLine {
  text?: string;
  speaker?: string | null;
  [k: string]: unknown;
}

export interface Citation {
  n: number;
  chapter_id: string | null;
  chapter_title: string;
  chapter_position: number;
  excerpt: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  meta: {
    found?: boolean;
    from_book?: string;
    inference?: string;
    mode?: "llm" | "passages_only" | "none";
    model?: string;
    is_local?: boolean;
    notice?: string;
    spoiler_safe?: boolean;
  };
  created_at: string;
}

export interface DownloadItem {
  kind: "full" | "m4b" | "chapter" | "extracted_text" | "original" | "processed_text" | "narration_text" | "zip";
  label: string;
  url: string | null;
  buildable?: boolean;
  size?: number;
  duration?: number;
  chapter_id?: string;
}

export interface SystemStatus {
  tts: TTSProviderInfo[];
  default_tts: string;
  ocr: { name: string; available: boolean; reason: string | null; languages: string[]; local: boolean }[];
  ocr_mode: string;
  llm: { name: string; model?: string; available: boolean; reason: string | null; is_local: boolean; privacy_note?: string };
  embeddings: { model: string; is_local: boolean };
  storage: { provider: string; free_bytes: number; local: boolean };
  limits: { max_file_size_mb: number; max_pages: number };
  privacy: { analytics: boolean; temp_file_ttl_hours: number; retention: string };
  languages: { code: string; name: string }[];
}

export interface Preferences {
  default_provider: string | null;
  default_voices: Record<string, { provider: string; voice_id: string }>;
  default_speed: number;
  playback_rate: number;
  skip_back_seconds: number;
  skip_forward_seconds: number;
  narration_cleanup: boolean;
  auto_analyze: boolean;
  build_full_audiobook: boolean;
  audio_format: string | null;
  audio_bitrate: string | null;
  analytics_opt_in: boolean;
  confirm_cloud_processing: boolean;
}

export interface Insights {
  chapter_summaries: { chapter_id: string; position: number; summary?: string; [k: string]: unknown }[];
  short_summary?: Record<string, unknown>;
  detailed_summary?: Record<string, unknown>;
  characters?: Record<string, unknown>;
  events?: Record<string, unknown>;
  themes?: Record<string, unknown>;
  glossary?: Record<string, unknown>;
}

/** Live snapshot pushed by /ws/books/{id}. */
export interface BookSnapshot {
  type: "book";
  book: { id: string; status: BookStatus; title: string; error: Book["error"]; total_duration: number | null };
  job: Job | null;
  chapters: Pick<Chapter, "id" | "position" | "title" | "audio_status" | "audio_progress" | "duration" | "audio_error" | "include_in_audio">[];
  finished: boolean;
}
