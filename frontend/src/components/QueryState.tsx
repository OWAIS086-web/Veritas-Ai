import { AlertOctagon, Inbox, RotateCw } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { ApiError } from "@/services/api";

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const title = error instanceof ApiError ? error.title : "Something went wrong";
  const detail =
    error instanceof ApiError
      ? error.detail
      : "The request could not be completed. Check your connection and try again.";
  return (
    <div role="alert" className="flex flex-col items-center gap-3 py-10 text-center">
      <AlertOctagon className="h-8 w-8 text-danger" aria-hidden />
      <div>
        <p className="font-medium">{title}</p>
        <p className="mt-1 max-w-md text-xs text-muted">{detail}</p>
        {error instanceof ApiError && error.requestId ? (
          <p className="mt-1 font-mono text-[11px] text-muted/70">request {error.requestId}</p>
        ) : null}
      </div>
      {onRetry ? (
        <Button variant="secondary" size="sm" icon={<RotateCw className="h-3.5 w-3.5" />} onClick={onRetry}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}

export function EmptyState({ title, children, action }: {
  title: string; children?: ReactNode; action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 py-10 text-center">
      <Inbox className="h-8 w-8 text-muted" aria-hidden />
      <div>
        <p className="font-medium">{title}</p>
        {children ? <div className="mt-1 max-w-md text-xs text-muted">{children}</div> : null}
      </div>
      {action}
    </div>
  );
}
