import { QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { RouterProvider } from "react-router-dom";

import { makeQueryClient } from "@/app/queryClient";
import { createRouter } from "@/app/router";
import { Toaster } from "@/components/ui/Toaster";
import { bootstrapSession } from "@/features/auth/session";

export function App() {
  const [queryClient] = useState(makeQueryClient);
  const [router] = useState(createRouter);
  useEffect(() => {
    void bootstrapSession();
  }, []);
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <Toaster />
    </QueryClientProvider>
  );
}
