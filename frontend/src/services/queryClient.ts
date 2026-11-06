import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "@/services/http";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: false,
      retry: (count, err) => {
        if (err instanceof ApiError && err.status >= 400 && err.status < 500) return false;
        // Server unreachable (restarting, sleeping laptop...): keep trying for about a minute.
        if (err instanceof ApiError && err.status === 0) return count < 8;
        return count < 2;
      },
      retryDelay: (attempt) => Math.min(8000, 700 * 2 ** attempt),
    },
  },
});

export const qk = {
  books: (params?: unknown) => ["books", params] as const,
  book: (id: string) => ["book", id] as const,
  chapters: (id: string) => ["chapters", id] as const,
  chapter: (id: string) => ["chapter", id] as const,
  playback: (id: string) => ["playback", id] as const,
  continue: ["continue"] as const,
  voices: (params?: unknown) => ["voices", params] as const,
  providers: ["providers"] as const,
  status: ["system-status"] as const,
  prefs: ["preferences"] as const,
  cast: (id: string) => ["cast", id] as const,
  chat: (id: string) => ["chat", id] as const,
  askStatus: (id: string) => ["ask-status", id] as const,
  insights: (id: string) => ["insights", id] as const,
  downloads: (id: string) => ["downloads", id] as const,
  estimate: (id: string) => ["estimate", id] as const,
  job: (id: string) => ["job", id] as const,
};
