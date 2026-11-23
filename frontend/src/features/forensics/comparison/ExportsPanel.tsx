import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { Badge, Mono } from "@/components/ui/primitives";
import { EXPORTS } from "@/features/forensics/comparison/labels";
import { startDownload } from "@/features/reports/download";
import { ApiError, api } from "@/services/api";
import { usePermission } from "@/stores/auth";
import { toast } from "@/stores/toast";
import type { ComparisonExportKind, ComparisonExportOut } from "@/types/api";

const STATUS_TONE = { queued: "evidence", completed: "primary", failed: "danger" } as const;

function Row({ comparisonId, kind, label, hint, latest }: {
  comparisonId: string;
  kind: ComparisonExportKind;
  label: string;
  hint: string;
  latest: ComparisonExportOut | undefined;
}) {
  const qc = useQueryClient();
  const canRun = usePermission("comparisons:run");
  const download = useMutation({
    mutationFn: (id: string) => api.comparisonExportDownload(id),
    onSuccess: (link) => startDownload(link.url),
    onError: (err) => toast.error("Download failed", err instanceof ApiError ? err.detail : undefined),
  });
  const regenerate = useMutation({
    mutationFn: () => api.createComparisonExport(comparisonId, kind),
    onSuccess: () => {
      toast.info("Export queued", `${label} is being generated from the current review state.`);
      void qc.invalidateQueries({ queryKey: ["comparison", comparisonId] });
    },
    onError: (err) => toast.error("Export not queued", err instanceof ApiError ? err.detail : undefined),
  });
  return (
    <li className="flex flex-wrap items-center gap-2 py-2">
      <div className="min-w-0 flex-1">
        <p className="text-sm">{label}</p>
        <p className="text-[11px] text-muted">
          {hint}
          {latest?.sha256 ? <> · SHA-256 <Mono>{latest.sha256.slice(0, 16)}…</Mono></> : null}
          {latest?.error ? <> · {latest.error}</> : null}
        </p>
      </div>
      {latest ? <Badge tone={STATUS_TONE[latest.status]}>{latest.status}</Badge> : <Badge>Not generated</Badge>}
      <Button size="sm" variant="secondary" icon={<Download className="h-4 w-4" />}
              disabled={latest?.status !== "completed"} loading={download.isPending}
              onClick={() => latest && download.mutate(latest.id)} aria-label={`Download ${label}`}>
        Download
      </Button>
      {canRun ? (
        <Button size="sm" variant="ghost" icon={<RefreshCw className="h-4 w-4" />} loading={regenerate.isPending}
                disabled={latest?.status === "queued"} onClick={() => regenerate.mutate()}
                aria-label={`Generate ${label} again`}>
          Regenerate
        </Button>
      ) : null}
    </li>
  );
}

/** The newest export of each kind, with download and regenerate actions. */
export function ExportsPanel({ comparisonId, exports }: { comparisonId: string; exports: ComparisonExportOut[] }) {
  return (
    <ul aria-label="Exports" className="divide-y divide-line">
      {EXPORTS.map((e) => (
        <Row key={e.kind} comparisonId={comparisonId} kind={e.kind} label={e.label} hint={e.hint}
             latest={exports.find((x) => x.kind === e.kind)} />
      ))}
    </ul>
  );
}
