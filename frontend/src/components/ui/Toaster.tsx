import { clsx } from "clsx";
import { CheckCircle2, Info, X, XCircle } from "lucide-react";

import { useToasts, type ToastTone } from "@/stores/toast";

const icon: Record<ToastTone, typeof Info> = { success: CheckCircle2, error: XCircle, info: Info };
const tone: Record<ToastTone, string> = {
  success: "text-primary",
  error: "text-danger",
  info: "text-evidence",
};

export function Toaster() {
  const { toasts, dismiss } = useToasts();
  return (
    <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2">
      {toasts.map((t) => {
        const Icon = icon[t.tone];
        return (
          <div key={t.id} role="status" className="panel pointer-events-auto flex gap-3 p-3 shadow-xl">
            <Icon className={clsx("mt-0.5 h-4 w-4 shrink-0", tone[t.tone])} aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{t.title}</p>
              {t.detail ? <p className="mt-0.5 break-words text-xs text-muted">{t.detail}</p> : null}
            </div>
            <button
              type="button"
              aria-label="Dismiss notification"
              onClick={() => dismiss(t.id)}
              className="rounded text-muted hover:text-ink"
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
          </div>
        );
      })}
    </div>
  );
}
