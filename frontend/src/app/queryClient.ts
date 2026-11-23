import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "@/services/api";

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: false,
        // Don't retry client errors (4xx); retry transient failures twice.
        retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
      },
    },
  });
}
