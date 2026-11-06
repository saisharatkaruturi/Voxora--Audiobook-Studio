export { clsx as cn } from "clsx";

/** 3725 -> "1:02:05", 65 -> "1:05" */
export function formatClock(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "0:00";
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mm = h ? String(m).padStart(2, "0") : String(m);
  return `${h ? `${h}:` : ""}${mm}:${String(sec).padStart(2, "0")}`;
}

/** 3725 -> "1h 2m", 300 -> "5 min", 40 -> "40 sec" */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))} sec`;
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  if (!h) return `${m} min`;
  return m ? `${h}h ${m}m` : `${h}h`;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let n = bytes;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n >= 10 || i === 0 ? Math.round(n) : n.toFixed(1)} ${units[i]}`;
}

export function formatNumber(n: number | null | undefined): string {
  return (n ?? 0).toLocaleString();
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`;
  if (diff < 86400 * 7) return `${Math.round(diff / 86400)} d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function pluralize(n: number, word: string, plural = `${word}s`): string {
  return `${n.toLocaleString()} ${n === 1 ? word : plural}`;
}

const KIND_LABELS: Record<string, string> = {
  title_page: "Title page",
  copyright: "Copyright",
  dedication: "Dedication",
  epigraph: "Epigraph",
  toc: "Contents",
  foreword: "Foreword",
  preface: "Preface",
  introduction: "Introduction",
  acknowledgements: "Acknowledgements",
  front_matter: "Front matter",
  prologue: "Prologue",
  part: "Part",
  chapter: "Chapter",
  epilogue: "Epilogue",
  afterword: "Afterword",
  appendix: "Appendix",
  glossary: "Glossary",
  bibliography: "Notes & references",
  author_bio: "About the author",
  advertisement: "Advertisement",
  back_matter: "Back matter",
};
export const CHAPTER_KINDS = Object.keys(KIND_LABELS);
export const kindLabel = (kind: string) => KIND_LABELS[kind] ?? kind;

/** Book listening fraction 0..1 from progress + duration. */
export function bookFraction(position: number | undefined, total: number | null | undefined): number {
  if (!position || !total) return 0;
  return Math.min(1, Math.max(0, position / total));
}
