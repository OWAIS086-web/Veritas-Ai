import { clsx } from "clsx";
import { forwardRef, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <section className={clsx("panel p-5", className)}>{children}</section>;
}

export function CardTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-4 flex items-center justify-between gap-3">
      <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-muted">{children}</h2>
      {action}
    </div>
  );
}

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
  hint?: string;
}

export const Field = forwardRef<HTMLInputElement, FieldProps>(function Field(
  { label, error, hint, id, className, ...rest },
  ref,
) {
  const inputId = id ?? `f-${label.toLowerCase().replace(/\W+/g, "-")}`;
  const describedBy = error ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined;
  return (
    <div className={clsx("space-y-1.5", className)}>
      <label htmlFor={inputId} className="block text-xs font-medium text-muted">
        {label}
      </label>
      <input
        ref={ref}
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={clsx(
          "h-10 w-full rounded-lg border bg-bg/60 px-3 text-sm text-ink placeholder:text-muted/60",
          "transition-colors focus:border-evidence/60",
          error ? "border-danger/60" : "border-line",
        )}
        {...rest}
      />
      {error ? (
        <p id={`${inputId}-error`} className="text-xs text-danger">
          {error}
        </p>
      ) : hint ? (
        <p id={`${inputId}-hint`} className="text-xs text-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
});

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label: string;
  hideLabel?: boolean;
}

export function Select({ label, hideLabel, id, className, children, ...rest }: SelectProps) {
  const selectId = id ?? `s-${label.toLowerCase().replace(/\W+/g, "-")}`;
  return (
    <div className={clsx("space-y-1.5", className)}>
      <label htmlFor={selectId} className={clsx("block text-xs font-medium text-muted",
                                                 hideLabel && "sr-only")}>
        {label}
      </label>
      <select
        id={selectId}
        className="h-10 w-full rounded-lg border border-line bg-bg/60 px-3 text-sm text-ink"
        {...rest}
      >
        {children}
      </select>
    </div>
  );
}

export type BadgeTone = "neutral" | "primary" | "evidence" | "warning" | "danger";
type Tone = BadgeTone;
const tones: Record<Tone, string> = {
  neutral: "border-line text-muted",
  primary: "border-primary/30 bg-primary/10 text-primary",
  evidence: "border-evidence/30 bg-evidence/10 text-evidence",
  warning: "border-warning/30 bg-warning/10 text-warning",
  danger: "border-danger/30 bg-danger/10 text-danger",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-medium",
                          tones[tone])}>
      {children}
    </span>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={clsx("animate-pulse rounded-md bg-elevated", className)} />;
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={clsx("font-mono text-xs tabular", className)}>{children}</span>;
}
