import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { api, refreshSession } from "@/services/api";
import { getStoredRefresh, useAuth } from "@/stores/auth";
import type { TokenPair } from "@/types/api";

/** Store a fresh token pair and load the profile it belongs to. */
export async function startSession(pair: TokenPair): Promise<void> {
  useAuth.getState().setTokens(pair);
  useAuth.getState().setMe(await api.me());
}

/** On app start, restore the session from the stored refresh token if there is one. */
export async function bootstrapSession(): Promise<void> {
  if (!getStoredRefresh()) {
    useAuth.getState().markAnonymous();
    return;
  }
  try {
    if (await refreshSession()) {
      useAuth.getState().setMe(await api.me());
      return;
    }
  } catch {
    /* fall through to anonymous */
  }
  useAuth.getState().clear();
}

export function useLogout(): () => Promise<void> {
  const qc = useQueryClient();
  return useCallback(async () => {
    const refresh = getStoredRefresh();
    try {
      if (refresh) await api.logout(refresh);
    } finally {
      useAuth.getState().clear();
      qc.clear();
    }
  }, [qc]);
}
