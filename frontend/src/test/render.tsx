import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { makeQueryClient } from "@/app/queryClient";
import { routes } from "@/app/router";
import { Toaster } from "@/components/ui/Toaster";
import { useAuth } from "@/stores/auth";
import type { MeResponse } from "@/types/api";

export function signIn(me: MeResponse) {
  useAuth.setState({ status: "authenticated", accessToken: "test-access", me });
}

export function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const client = makeQueryClient();
  client.setDefaultOptions({ queries: { ...client.getDefaultOptions().queries, retry: false } });
  return {
    router,
    ...render(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
        <Toaster />
      </QueryClientProvider>,
    ),
  };
}
