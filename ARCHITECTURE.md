# VOXORA architecture

```
 React + TypeScript (Vite)                     FastAPI (Python)
┌─────────────────────────────┐   REST /api   ┌──────────────────────────────┐
│ pages · features · stores   │ ────────────▶ │ api/routes                    │
│ TanStack Query (server data)│   WS /ws      │   books · chapters · jobs ·    │
│ Zustand (auth, player)      │ ◀──────────── │   player · voices · ai · media │
│ three.js / R3F (VOXORA Book)│  /media (HMAC │                               │
│ <audio> + Web Audio analyser│  signed URLs) │ services (ingest, generation, │
└─────────────────────────────┘               │  rag, cast, insights, export) │
                                              │        │           ▲          │
                                              │        ▼           │          │
                                              │  generation_jobs (DB queue)   │
                                              │        │  claimed by          │
                                              │  WorkerPool threads / process │
                                              │        │                      │
                                              │ providers: TTS · OCR · LLM ·  │
                                              │  embeddings · rerank · storage│
                                              └──────────────────────────────┘
                                                SQLite/Postgres · local/S3 storage
```

## Pipeline

```
upload ─▶ sniff (magic bytes, never the filename) ─▶ store original
      ─▶ ANALYZE job:
           extract  (PyMuPDF text layer / python-docx / EbookLib / TXT)
           OCR      (only pages without a usable text layer; RapidOCR · Tesseract · EasyOCR)
           clean    (headers/footers, page numbers, de-hyphenation, unwrap, OCR fixes)
           language (per paragraph, script-aware)
           structure(outline/TOC → heading styles → numbering patterns → length fallback;
                     front matter, parts, epilogue, appendices classified)
           cover    (embedded cover, else first page, else generated typographic cover)
      ─▶ Book Studio edits (chapters/paragraphs in the DB; original never modified)
      ─▶ GENERATE job, per chapter:
           plan: paragraphs → sentences → provider-sized chunks (+ narration cleanup,
                 per-language voice, AI Cast speaker spans)
           synthesize each chunk (cache key = SHA256(provider signature + voice + speed/
                 pitch/volume/pauses + text)); reuse cached FLAC segments
           trim / shorten long pauses (timings remapped) → raw PCM on disk (constant memory)
           encode (loudnorm, optional compression) → MP3/M4A/WAV + ID3/MP4 tags
           sentence timings (provider marks, else approximated) for read-along
      ─▶ full audiobook: concat + chapter markers
```

## Background jobs

`generation_jobs` is a durable queue: workers claim rows with an atomic `UPDATE … WHERE status='queued'`, send heartbeats, and a janitor re-queues jobs whose worker died. Jobs support pause (checked between chunks), resume, cancel, and retry with exponential backoff for retryable provider errors. A failed chapter is marked with a user-facing message; resuming skips chapters whose content hash is unchanged. The worker runs inside the API process by default (`RUN_WORKER_IN_PROCESS=true`) or as `python -m app.workers.runner` for separate scaling. Redis/Celery were intentionally avoided: the app must run with one command on Windows; `workers/queue.py` is the seam for a Redis-backed queue.

Progress reaches the UI over WebSockets (`/ws/books/{id}`, `/ws/jobs/{id}`), which read snapshots from the database, so they work even when the worker is another process.

## Providers

Every external capability sits behind an interface chosen by configuration: `TTSProvider` (Piper, SAPI, Edge, OpenAI-compatible, ElevenLabs), `OCRProvider`, `LLMProvider` (auto, Ollama, OpenAI-compatible, Anthropic Claude), `EmbeddingProvider` (fastembed, Ollama, OpenAI, hashing), a cross-encoder reranker, and `StorageProvider` (local, S3 with presigned URLs). Each provider declares `is_local` and a privacy note that the UI shows before any text leaves the machine.

## Ask the Book (RAG)

Chapters are chunked (~170 words, overlap, paragraph-aware) into `book_embeddings` under the namespace `books/{book_id}`; every query filters on that namespace, so books never mix. Retrieval blends dense cosine similarity (English: `bge-base-en-v1.5`; other languages: a multilingual model) with BM25, takes the top 24, and reranks them with a local cross-encoder (Jina reranker). Chapter-specific questions ("chapter 5") are routed to that chapter; spoiler-safe mode limits retrieval to chapters already listened to. The LLM must answer in a JSON schema that separates `from_book` (with [n] citations) from `inference`; without an LLM the best passages are returned, clearly labelled.

## Security

Password hashing (scrypt), HMAC-signed bearer tokens, per-user authorization on every book/chapter/job, HMAC-signed expiring media URLs (audio elements can't send headers), content sniffing and executable rejection, sanitized filenames, storage-key validation against path traversal, upload size limits, rate limits on auth/upload/preview/ask, security headers, re-encoded cover images, temp-file cleanup.

## Frontend

- **Design system:** tokens in `styles/index.css` (`@theme`), brand in `config/brand.ts`, motion constants in `config/motion.ts`. Glass for surfaces, neomorphism for controls.
- **Brand system:** `components/brand` (mark, wordmark with living "O", splash, CSS book fallback, `BookStage`).
- **3D:** `components/3d` — a hinged book with deforming pages (vertex updates), a GPU particle system (one draw call, GLSL) that turns into the waveform, modes `closed | open | flowing | playing | absorb | sealed`. Lazy-loaded; pauses off-screen/hidden; reduced-motion aware; falls back to CSS without WebGL.
- **Player:** a single `<audio>` outside React (`stores/player.ts`), progress saved every 8 s, on pause, chapter change and page hide (keepalive), with a local copy for offline resilience; a Web Audio analyser (same-origin media only) drives the waveform and living cover.


