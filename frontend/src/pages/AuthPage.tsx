import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Logo } from "@/components/layout/Logo";
import { Button } from "@/components/ui/Button";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { Field, Input } from "@/components/ui/Form";
import { Notice } from "@/components/ui/Feedback";
import { authApi } from "@/services/api";
import { errorMessage } from "@/services/http";
import { authConfig, supabase, supabaseError } from "@/services/supabase";
import { useAuth } from "@/stores/auth";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { brand } from "@/config/brand";

type Outcome = { kind: "signed-in" } | { kind: "check-email"; email: string } | { kind: "reset-sent"; email: string };

export default function AuthPage({ mode }: { mode: "signin" | "register" }) {
  const { token, setSession, setToken, setUser, clear } = useAuth();
  useDocumentTitle(mode === "register" ? "Create account" : "Sign in");
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  // Arriving from a password-reset email: go straight to choosing a new password.
  const from = params.get("reset") ? "/settings#profile" : ((location.state as { from?: string } | null)?.from ?? "/library");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [forgot, setForgot] = useState(false);
  const [notice, setNotice] = useState<Outcome | null>(null);
  const config = useQuery({ queryKey: ["auth-config"], queryFn: authConfig, staleTime: Infinity });
  const viaSupabase = config.data?.provider === "supabase";
  const firstUser = !viaSupabase && config.data && !config.data.has_users;
  const isRegister = !forgot && (mode === "register" || (mode === "signin" && !!firstUser));

  const submit = useMutation({
    mutationFn: async (): Promise<Outcome> => {
      if (!viaSupabase) {
        const { token, user } = isRegister
          ? await authApi.register(email, password, name || email.split("@")[0])
          : await authApi.login(email, password);
        setSession(token, user);
        return { kind: "signed-in" };
      }
      const client = await supabase();
      if (!client) throw new Error("Sign-in isn't configured on this server.");
      const back = `${window.location.origin}/signin`;
      if (forgot) {
        const { error } = await client.auth.resetPasswordForEmail(email, { redirectTo: `${back}?reset=1` });
        if (error) throw new Error(supabaseError(error));
        return { kind: "reset-sent", email };
      }
      const { data, error } = isRegister
        ? await client.auth.signUp({
            email,
            password,
            options: { emailRedirectTo: back, data: { display_name: name.trim() || email.split("@")[0] } },
          })
        : await client.auth.signInWithPassword({ email, password });
      if (error) throw new Error(supabaseError(error));
      // Sign-up with email confirmation on: no session until the link is opened.
      if (!data.session) return { kind: "check-email", email };
      setToken(data.session.access_token);
      try {
        // Creates (or links) the VOXORA account; refuses when sign-ups are closed.
        setUser(await authApi.me());
      } catch (err) {
        clear();
        await client.auth.signOut().catch(() => undefined);
        throw err;
      }
      return { kind: "signed-in" };
    },
    onSuccess: (outcome) => {
      if (outcome.kind === "signed-in") navigate(from, { replace: true });
      else setNotice(outcome);
    },
  });

  const oauth = useMutation({
    mutationFn: async (provider: "google") => {
      const client = await supabase();
      if (!client) throw new Error("Sign-in isn't configured on this server.");
      // Leaves the page for Google; Supabase brings the browser back to /signin signed in.
      const { error } = await client.auth.signInWithOAuth({
        provider,
        options: { redirectTo: `${window.location.origin}/signin${params.get("reset") ? "?reset=1" : ""}` },
      });
      if (error) throw new Error(supabaseError(error));
    },
  });
  const showGoogle = viaSupabase && !forgot && (config.data?.oauth_providers ?? []).includes("google");

  if (token && !submit.isPending) return <Navigate to={from} replace />;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    setNotice(null);
    submit.mutate();
  };

  const title = forgot
    ? "Reset your password"
    : isRegister
      ? firstUser
        ? `Welcome to ${brand.name}`
        : `Create your ${brand.name} account`
      : `Welcome to ${brand.name}`;
  const subtitle = forgot
    ? "We'll email you a link to choose a new one."
    : firstUser
      ? "You're the first one here, so this account becomes the admin."
      : isRegister
        ? "Your own private library of stories."
        : "Continue your listening journey.";

  return (
    <div className="relative flex min-h-dvh flex-col items-center justify-center px-5 py-12">
      <ThemeToggle className="absolute top-5 right-5" />
      <Logo to="/" className="mb-10" />
      <div className="surface w-full max-w-sm animate-fade-up p-7">
        <h1 className="font-display text-2xl text-paper-50">{title}</h1>
        <p className="mt-1.5 text-sm text-paper-400">{subtitle}</p>
        {isRegister && config.data && !config.data.registration_open && (
          <Notice kind="warning" className="mt-5">
            Registration is closed on this server. Ask the admin for an account.
          </Notice>
        )}
        {notice?.kind === "check-email" && (
          <Notice kind="success" className="mt-5" title="Check your inbox">
            We sent a confirmation link to {notice.email}. Open it to finish creating your account.
          </Notice>
        )}
        {notice?.kind === "reset-sent" && (
          <Notice kind="success" className="mt-5" title="Check your inbox">
            If {notice.email} has an account, a password reset link is on its way.
          </Notice>
        )}
        {showGoogle && (
          <div className="mt-6">
            <Button
              variant="secondary"
              size="lg"
              className="w-full"
              loading={oauth.isPending}
              icon={<GoogleMark />}
              onClick={() => oauth.mutate("google")}
            >
              Continue with Google
            </Button>
            {oauth.isError && (
              <Notice kind="error" className="mt-3">
                {errorMessage(oauth.error)}
              </Notice>
            )}
            <div className="mt-6 flex items-center gap-3 text-xs text-paper-500" aria-hidden="true">
              <span className="h-px flex-1 bg-white/10" />
              or {isRegister ? "sign up" : "sign in"} with email
              <span className="h-px flex-1 bg-white/10" />
            </div>
          </div>
        )}
        <form className={showGoogle ? "mt-4 space-y-4" : "mt-6 space-y-4"} onSubmit={onSubmit} noValidate={false}>
          {isRegister && (
            <Field label="Your name" htmlFor="name">
              <Input id="name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Asha" maxLength={120} />
            </Field>
          )}
          <Field label="Email" htmlFor="email">
            <Input id="email" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          {!forgot && (
            <Field label="Password" htmlFor="password" hint={isRegister ? "At least 8 characters." : undefined}>
              <Input
                id="password"
                type="password"
                required
                minLength={isRegister ? 8 : undefined}
                autoComplete={isRegister ? "new-password" : "current-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>
          )}
          {submit.isError && <Notice kind="error">{errorMessage(submit.error)}</Notice>}
          <Button type="submit" variant="primary" className="w-full" size="lg" loading={submit.isPending} disabled={config.isPending}>
            {forgot ? "Send reset link" : isRegister ? "Create account" : "Sign in"}
          </Button>
          {viaSupabase && !isRegister && (
            <button
              type="button"
              className="w-full text-center text-sm text-paper-400 hover:text-orchid-400"
              onClick={() => {
                setForgot(!forgot);
                setNotice(null);
                submit.reset();
              }}
            >
              {forgot ? "Back to sign in" : "Forgot password?"}
            </button>
          )}
        </form>
      </div>
      {!firstUser && !forgot && (
        <p className="mt-6 text-sm text-paper-400">
          {isRegister ? (
            <>
              Already have an account?{" "}
              <Link to="/signin" state={location.state} className="text-orchid-400 hover:underline">
                Sign in
              </Link>
            </>
          ) : (
            <>
              New here?{" "}
              <Link to="/register" state={location.state} className="text-orchid-400 hover:underline">
                Create an account
              </Link>
            </>
          )}
        </p>
      )}
    </div>
  );
}

function GoogleMark() {
  return (
    <svg viewBox="0 0 48 48" className="size-5" aria-hidden="true">
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
      <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
    </svg>
  );
}
