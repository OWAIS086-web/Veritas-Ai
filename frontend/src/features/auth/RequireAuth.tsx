import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { Logo } from "@/components/Logo";
import { useAuth } from "@/stores/auth";

export function RequireAuth({ children }: { children: ReactNode }) {
  const status = useAuth((s) => s.status);
  const location = useLocation();
  if (status === "unknown") {
    return (
      <div className="flex min-h-screen items-center justify-center" role="status" aria-live="polite">
        <div className="flex flex-col items-center gap-3 text-muted">
          <div className="animate-pulse"><Logo /></div>
          <span className="text-xs">Restoring session…</span>
        </div>
      </div>
    );
  }
  if (status === "anonymous") {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}
