import { clsx } from "clsx";
import type { LucideIcon } from "lucide-react";

import type { Metric } from "@/types/api";

interface MetricCardProps {
  label: string;
  metric: Metric;
  icon: LucideIcon;
  format?: (value: number) => string;
  tone?: "primary" | "evidence" | "warning" | "danger";
}

const toneText = {
  primary: "text-primary",
  evidence: "text-evidence",
  warning: "text-warning",
  danger: "text-danger",
} as const;

export function MetricCard({ label, metric, icon: Icon, format, tone = "evidence" }: MetricCardProps) {
  const pending = !metric.available;
  const value = metric.value;
  return (
    <div className={clsx("panel p-4", pending && "border-dashed")}
         aria-label={`${label}: ${pending ? "available in a later phase" : value ?? "no data"}`}>
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted">{label}</p>
        <Icon className={clsx("h-4 w-4", pending ? "text-muted/50" : toneText[tone])} aria-hidden />
      </div>
      {pending ? (
        <p className="mt-3 text-xs text-warning/90">Available in a later phase</p>
      ) : (
        <p className="tabular mt-2 font-mono text-2xl font-semibold">
          {value === null || value === undefined ? "—" : format ? format(value) : value.toLocaleString()}
        </p>
      )}
      {!pending && metric.note ? <p className="mt-1 text-[11px] text-muted">{metric.note}</p> : null}
    </div>
  );
}
