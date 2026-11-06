import { create } from "zustand";
import type { User } from "@/types/api";

const TOKEN_KEY = "abs.token";

function readToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function writeToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable (private mode): the session lasts until reload */
  }
}

interface AuthState {
  token: string | null;
  user: User | null;
  setSession: (token: string, user: User) => void;
  /** A new access token for the same session (Supabase refreshes it in the background). */
  setToken: (token: string) => void;
  setUser: (user: User) => void;
  /** Forget the session locally (no call to the sign-in provider). */
  clear: () => void;
  /** Sign out everywhere: locally and, when used, from Supabase. */
  signOut: () => void;
}

export const useAuth = create<AuthState>((set, get) => ({
  token: readToken(),
  user: null,
  setSession: (token, user) => {
    writeToken(token);
    set({ token, user });
  },
  setToken: (token) => {
    writeToken(token);
    set({ token });
  },
  setUser: (user) => set({ user }),
  clear: () => {
    writeToken(null);
    set({ token: null, user: null });
  },
  signOut: () => {
    get().clear();
    void import("@/services/supabase").then((m) => m.supabaseSignOut());
  },
}));
