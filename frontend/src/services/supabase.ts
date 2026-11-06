import type { SupabaseClient } from "@supabase/supabase-js";
import { authApi, type AuthConfig } from "@/services/api";
import { useAuth } from "@/stores/auth";

/**
 * Supabase Auth, when the server is configured for it (GET /api/auth/config).
 *
 * The browser signs in with Supabase; its access token is what the VOXORA API
 * receives as `Authorization: Bearer ...`. Supabase refreshes that token in the
 * background and we mirror each new one into the auth store.
 */

let configPromise: Promise<AuthConfig> | null = null;
let clientPromise: Promise<SupabaseClient | null> | null = null;

export function authConfig(): Promise<AuthConfig> {
  configPromise ??= authApi.config().catch((err) => {
    configPromise = null; // retry next time (server may be starting)
    throw err;
  });
  return configPromise;
}

export function supabase(): Promise<SupabaseClient | null> {
  clientPromise ??= (async () => {
    const cfg = await authConfig();
    if (cfg.provider !== "supabase" || !cfg.supabase_url || !cfg.supabase_anon_key) return null;
    const { createClient } = await import("@supabase/supabase-js");
    const client = createClient(cfg.supabase_url, cfg.supabase_anon_key, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true, flowType: "pkce" },
    });
    client.auth.onAuthStateChange((event, session) => {
      const store = useAuth.getState();
      if (session?.access_token) {
        if (session.access_token !== store.token) store.setToken(session.access_token);
      } else if (event === "SIGNED_OUT") {
        store.clear();
      }
    });
    return client;
  })().catch((err) => {
    clientPromise = null;
    throw err;
  });
  return clientPromise;
}

/** Start Supabase early so a sign-in link (email confirmation, password reset) is picked up. */
export function initAuth() {
  void supabase()
    .then(async (client) => {
      if (!client) return;
      const { data } = await client.auth.getSession();
      if (data.session) useAuth.getState().setToken(data.session.access_token);
      else if (useAuth.getState().token) useAuth.getState().clear(); // stale token from built-in accounts
    })
    .catch(() => {
      /* backend unreachable: the connection banner covers it */
    });
}

export async function supabaseSignOut() {
  const client = await supabase().catch(() => null);
  if (client) await client.auth.signOut().catch(() => undefined);
}

/** A readable message for a Supabase Auth error. */
export function supabaseError(err: { message?: string; code?: string } | null | undefined): string {
  if (!err) return "Something went wrong.";
  switch (err.code) {
    case "invalid_credentials":
      return "Incorrect email or password.";
    case "email_not_confirmed":
      return "Confirm your email first: open the link we sent to your inbox.";
    case "user_already_exists":
      return "An account with this email already exists. Sign in instead.";
    case "weak_password":
      return err.message || "Choose a stronger password.";
    case "over_email_send_rate_limit":
    case "over_request_rate_limit":
      return "Too many attempts. Wait a minute and try again.";
    default:
      return err.message || "Something went wrong.";
  }
}
