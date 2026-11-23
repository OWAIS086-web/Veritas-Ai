import { useMutation, useQuery } from "@tanstack/react-query";
import { GitCompareArrows } from "lucide-react";
import { Link } from "react-router-dom";

import { EmptyState, ErrorState } from "@/components/QueryState";
import { Button } from "@/components/ui/Button";
import { Card, CardTitle, Mono, Skeleton } from "@/components/ui/primitives";
import { SeverityBadge, StatusBadgeFinding } from "@/features/findings/badges";
import { findingTypeLabel, formatMoney } from "@/features/findings/labels";
import { api, ApiError } from "@/services/api";
import { usePermission } from "@/stores/auth";
import { toast } from "@/stores/toast";
import type { CaseOut } from "@/types/api";

/** Findings of one case, plus the action that re-runs the comparison. */
export function CaseFindingsPanel({ caseItem, onJob, busy }: {
  caseItem: CaseOut; onJob: (jobId: string) => void; busy: boolean;
}) {
  const canRun = usePermission("findings:run");
  const findings = useQuery({
    queryKey: ["case-findings", caseItem.id],
    queryFn: () => api.caseFindings(caseItem.id),
  });
  const compare = useMutation({
    mutationFn: () => api.compareCase(caseItem.id),
    onSuccess: (res) => { onJob(res.job_id); toast.info("Comparison queued", "Findings update when it finishes."); },
    onError: (err) => toast.error("Could not queue the comparison", err instanceof ApiError ? err.detail : undefined),
  });
  const neverCompared = caseItem.compared_at == null;

  return (
    <Card className="mb-6">
      <CardTitle action={
        <div className="flex items-center gap-3">
          {caseItem.compared_at ? (
            <Link to={`/graph?case=${caseItem.id}`} className="text-xs normal-case tracking-normal text-evidence hover:underline">
              Open graph
            </Link>
          ) : null}
          {canRun && caseItem.documents_completed > 0 ? (
            <Button size="sm" variant="secondary" icon={<GitCompareArrows className="h-4 w-4" />}
                    loading={compare.isPending} disabled={busy} onClick={() => compare.mutate()}>
              Compare documents
            </Button>
          ) : null}
        </div>
      }>
        Findings
        {caseItem.compared_at ? (
          <span className="ml-2 normal-case tracking-normal text-muted/80">
            compared {new Date(caseItem.compared_at).toLocaleString()}
          </span>
        ) : null}
      </CardTitle>
      {findings.isPending ? <Skeleton className="h-16" /> : findings.isError ? (
        <ErrorState error={findings.error} onRetry={() => void findings.refetch()} />
      ) : findings.data.length === 0 ? (
        <EmptyState title={neverCompared ? "Not compared yet" : "No findings"}>
          {neverCompared
            ? "The documents are compared automatically when processing finishes."
            : "The last comparison found no inconsistencies between the processed documents."}
        </EmptyState>
      ) : (
        <ul className="divide-y divide-line" aria-label="Case findings">
          {findings.data.map((f) => (
            <li key={f.id} className="flex flex-wrap items-center gap-3 py-2.5">
              <SeverityBadge severity={f.severity} />
              <Link to={`/findings/${f.id}`} className="min-w-0 flex-1 truncate text-sm font-medium hover:text-evidence">
                {f.title}
              </Link>
              <span className="text-xs text-muted">{findingTypeLabel(f.type)}</span>
              {f.difference ? <Mono>{formatMoney(f.difference, f.currency)}</Mono> : null}
              <span className="text-xs text-muted">
                {f.evidence_status === "absence" ? "absence" : `${f.evidence_count} evidence`}
              </span>
              <StatusBadgeFinding status={f.status} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
