import { AlertTriangle, Info, OctagonAlert, ShieldQuestion } from "lucide-react";

import { Badge } from "@/components/ui/primitives";
import { STATUS_LABELS } from "@/features/findings/labels";
import type { FindingStatus } from "@/types/api";

const SEVERITY = {
  high: { tone: "danger", icon: OctagonAlert },
  medium: { tone: "warning", icon: AlertTriangle },
  low: { tone: "evidence", icon: ShieldQuestion },
  info: { tone: "neutral", icon: Info },
} as const;

/** Severity is always shown with a label and an icon, never by color alone. */
export function SeverityBadge({ severity }: { severity: string }) {
  const s = SEVERITY[severity as keyof typeof SEVERITY] ?? SEVERITY.info;
  const Icon = s.icon;
  return (
    <Badge tone={s.tone}>
      <Icon className="h-3 w-3" aria-hidden />
      {severity}
    </Badge>
  );
}

export function StatusBadgeFinding({ status }: { status: FindingStatus }) {
  const tone = status === "confirmed_observation" ? "danger"
    : status === "dismissed" || status === "resolved" ? "neutral"
    : status === "needs_more_evidence" ? "warning" : "evidence";
  return <Badge tone={tone}>{STATUS_LABELS[status]}</Badge>;
}
