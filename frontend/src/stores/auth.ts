import { create } from "zustand";

import type { MeResponse, TokenPair } from "@/types/api";

/**
 * Session state. The access token lives only in memory. The refresh token is kept in
 * localStorage so a page reload can restore the session; it is rotated on every use and
 * reuse revokes the whole session family server-side. (Hardening candidate for the
 * security phase: move it to an httpOnly SameSite cookie.)
 */
const REFRESH_KEY = "veritas.refresh";

type Status = "unknown" | "authenticated" | "anonymous";

interface AuthState {
  status: Status;
  accessToken: string | null;
  me: MeResponse | null;
  setTokens: (pair: TokenPair) => void;
  setMe: (me: MeResponse) => void;
  clear: () => void;
  markAnonymous: () => void;
}

export const getStoredRefresh = (): string | null => {
  try {
    return window.localStorage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
};

export const useAuth = create<AuthState>((set) => ({
  status: "unknown",
  accessToken: null,
  me: null,
  setTokens: (pair) => {
    window.localStorage.setItem(REFRESH_KEY, pair.refresh_token);
    set({ accessToken: pair.access_token });
  },
  setMe: (me) => set({ me, status: "authenticated" }),
  clear: () => {
    window.localStorage.removeItem(REFRESH_KEY);
    set({ accessToken: null, me: null, status: "anonymous" });
  },
  markAnonymous: () => set({ status: "anonymous" }),
}));

export const hasPermission = (permission: string): boolean =>
  useAuth.getState().me?.permissions.includes(permission) ?? false;

export const usePermission = (permission: string): boolean =>
  useAuth((s) => s.me?.permissions.includes(permission) ?? false);
