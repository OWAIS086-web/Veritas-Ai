import { CheckCircle2, CircleDashed, Loader2, UploadCloud, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/primitives";

const STATUS = {
  uploaded: { tone: "neutral", label: "Queued", Icon: UploadCloud },
  processing: { tone: "evidence", label: "Processing", Icon: Loader2 },
  completed: { tone: "primary", label: "Completed", Icon: CheckCircle2 },
  failed: { tone: "danger", label: "Failed", Icon: XCircle },
} as const;

/** Document status with an icon and a word, never color alone. */
export function StatusBadge({ status, stage }: { status: string; stage?: string | null }) {
  const s = STATUS[status as keyof typeof STATUS] ?? { tone: "neutral", label: status, Icon: CircleDashed };
  return (
    <Badge tone={s.tone}>
      <s.Icon className={`h-3 w-3 ${status === "processing" ? "animate-spin" : ""}`} aria-hidden />
      {s.label}
      {status === "processing" && stage ? <span className="text-muted">· {stage}</span> : null}
    </Badge>
  );
}

export function FieldStatus({ status, reason }: { status: string; reason: string | null }) {
  return status === "extracted" ? (
    <Badge tone="primary"><CheckCircle2 className="h-3 w-3" aria-hidden />Extracted</Badge>
  ) : (
    <Badge tone="warning">
      <CircleDashed className="h-3 w-3" aria-hidden />
      Uncertain{reason ? `: ${reason.replaceAll("_", " ")}` : ""}
    </Badge>
  );
}
