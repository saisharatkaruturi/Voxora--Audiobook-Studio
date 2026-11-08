import { useAuth } from "@/stores/auth";
import { useConnection } from "@/stores/connection";
import type { ApiErrorBody } from "@/types/api";

/** An error returned by the API, carrying the backend's code and human message. */
export class ApiError extends Error {
  code: string;
  status: number;
  retryable: boolean;
  details: Record<string, unknown>;

  constructor(status: number, body: Partial<ApiErrorBody>) {
    super(body.message || `Request failed (${status})`);
    this.status = status;
    this.code = body.code || `http_${status}`;
    this.retryable = !!body.retryable;
    this.details = body.details || {};
  }
}

export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ?? "";

type Json = Record<string, unknown> | unknown[];

export interface RequestOptions {
  method?: string;
  body?: Json | FormData;
  query?: Record<string, string | number | boolean | null | undefined>;
  signal?: AbortSignal;
  keepalive?: boolean;
}

export function apiUrl(path: string, query?: RequestOptions["query"]): string {
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${url}${url.includes("?") ? "&" : "?"}${qs}` : url;
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const token = useAuth.getState().token;
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (opts.body instanceof FormData) body = opts.body;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(apiUrl(path, opts.query), {
      method: opts.method ?? (body ? "POST" : "GET"),
      headers,
      body,
      signal: opts.signal,
      keepalive: opts.keepalive,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    useConnection.getState().setOffline(true);
    throw new ApiError(0, {
      code: "network_error",
      message: "Can't reach the VOXORA server. Check that the backend is running.",
      retryable: true,
    });
  }
  // Any HTTP response (even an error) means the server is reachable again.
  useConnection.getState().setOffline(res.status === 502 || res.status === 503 || res.status === 504);
  if (res.status === 401 && token) {
    useAuth.getState().signOut();
  }
  if (!res.ok) {
    let err: Partial<ApiErrorBody> = {};
    try {
      err = ((await res.json()) as { error?: ApiErrorBody }).error ?? {};
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, err);
  }
  if (res.status === 204) return undefined as T;
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? await res.json() : await res.text()) as T;
}

/** Download an authenticated endpoint (not a signed media URL) as a file. */
export async function downloadAuthenticated(path: string, fallbackName: string) {
  const token = useAuth.getState().token;
  const res = await fetch(apiUrl(path), { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) {
    let err: Partial<ApiErrorBody> = {};
    try {
      err = ((await res.json()) as { error?: ApiErrorBody }).error ?? {};
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, err);
  }
  const disposition = res.headers.get("content-disposition") ?? "";
  const name = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? fallbackName;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export function wsUrl(path: string): string {
  const token = useAuth.getState().token ?? "";
  // Hosts that can't proxy WebSockets (e.g. Vercel) point VITE_WS_BASE straight at the backend.
  const wsBase = (import.meta.env.VITE_WS_BASE as string | undefined)?.replace(/\/$/, "");
  const base = wsBase || API_BASE || window.location.origin;
  const url = new URL(path, base.endsWith("/") ? base : base + "/");
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.searchParams.set("token", token);
  return url.toString();
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Unexpected error.";
}
