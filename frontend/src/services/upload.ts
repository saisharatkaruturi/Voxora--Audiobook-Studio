import { ApiError, apiUrl } from "@/services/http";
import { useAuth } from "@/stores/auth";
import type { Book, Job } from "@/types/api";

export const ACCEPTED_EXTENSIONS = [".pdf", ".epub", ".docx", ".txt", ".md", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"];

export function validateFile(file: File, maxMb: number): string | null {
  const ext = file.name.includes(".") ? file.name.slice(file.name.lastIndexOf(".")).toLowerCase() : "";
  if (!ACCEPTED_EXTENSIONS.includes(ext)) {
    return `"${file.name}" isn't a supported format. Use PDF, EPUB, DOCX, TXT, or page images (JPG, PNG).`;
  }
  if (file.size === 0) return `"${file.name}" is empty.`;
  if (file.size > maxMb * 1024 * 1024) return `"${file.name}" is larger than the ${maxMb} MB limit.`;
  return null;
}

/** Upload with real progress events (fetch doesn't expose upload progress). */
export function uploadBook(
  file: File,
  opts: { language: string; ocrMode: string; autoAnalyze: boolean },
  onProgress: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<{ book: Book; job: Job | null }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", apiUrl("/api/books"));
    const token = useAuth.getState().token;
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* ignore */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as { book: Book; job: Job | null });
      else reject(new ApiError(xhr.status, (body as { error?: ApiError })?.error ?? { message: `Upload failed (${xhr.status}).` }));
    };
    xhr.onerror = () => reject(new ApiError(0, { code: "network_error", message: "The upload was interrupted. Check that the server is running and try again." }));
    xhr.onabort = () => reject(new DOMException("Upload cancelled", "AbortError"));
    signal?.addEventListener("abort", () => xhr.abort());
    const form = new FormData();
    form.append("file", file);
    form.append("auto_analyze", String(opts.autoAnalyze));
    form.append("language", opts.language);
    form.append("ocr_mode", opts.ocrMode);
    xhr.send(form);
  });
}
