import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { useState } from "react";

import { ErrorState } from "@/components/QueryState";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardTitle, Mono, Skeleton } from "@/components/ui/primitives";
import { ExportsPanel } from "@/features/forensics/comparison/ExportsPanel";
import { FindingsPanel } from "@/features/forensics/comparison/FindingsPanel";
import {
  ACTIVE_STATUSES, COMPARISON_STATUS, STAGE_LABEL, VLM_STATUS,
} from "@/features/forensics/comparison/labels";
import { type PaneDoc, SyncedViewer } from "@/features/forensics/comparison/SyncedViewer";
import { ApiError, api } from "@/services/api";
import { usePermission } from "@/stores/auth";
import { toast } from "@/stores/toast";
import type { ComparisonDetail, ComparisonFindingOut } from "@/types/api";

interface PageRow {
  test_page: number;
  original_page: number;
  alignment: string;
  page_ssim: number;
  text_compared: boolean;
  test_text_method: string | null;
}

function Progress({ detail }: { detail: ComparisonDetail }) {
  const qc = useQueryClient();
  const canRun = usePermission("comparisons:run");
  const retry = useMutation({
    mutationFn: () => api.retryComparison(detail.id),
    onSuccess: () => {
      toast.info("Comparison queued again");
      void qc.invalidateQueries({ queryKey: ["comparison", detail.id] });
      void qc.invalidateQueries({ queryKey: ["comparisons", detail.case_id] });
    },
    onError: (err) => toast.error("Retry failed", err instanceof ApiError ? err.detail : undefined),
  });
  if (detail.status === "failed") {
    return (
      <div role="alert" className="space-y-2">
        <p className="text-sm text-danger">The comparison failed: {detail.error ?? "unknown error"}</p>
        {canRun ? (
          <Button size="sm" variant="secondary" icon={<RotateCcw className="h-4 w-4" />}
                  loading={retry.isPending} onClick={() => retry.mutate()}>Retry comparison</Button>
        ) : null}
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <p className="text-sm">{STAGE_LABEL[detail.stage ?? ""] ?? COMPARISON_STATUS[detail.status].label}</p>
      <div className="h-2 w-full overflow-hidden rounded bg-elevated" role="progressbar" aria-label="Comparison progress"
           aria-valuemin={0} aria-valuemax={100} aria-valuenow={detail.progress}>
        <div className="h-full bg-evidence transition-all" style={{ width: `${detail.progress}%` }} />
      </div>
      <p className="text-xs text-muted">Progress is saved by the worker; this view refreshes every 2 seconds.</p>
    </div>
  );
}

function Summary({ detail }: { detail: ComparisonDetail }) {
  const s = detail.summary as Record<string, unknown>;
  const pages = (s["pages"] ?? []) as PageRow[];
  const vlm = (s["vlm"] ?? null) as Record<string, unknown> | null;
  const side = (k: "original" | "test") => (s[k] ?? {}) as Record<string, unknown>;
  return (
    <div className="space-y-3 text-xs">
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        {(["original", "test"] as const).map((k) => (
          <div key={k} className="contents">
            <dt className="capitalize text-muted">{k} SHA-256</dt>
            <dd className="break-all"><Mono>{String(side(k)["sha256"] ?? "-")}</Mono></dd>
          </div>
        ))}
      </dl>
      <table className="w-full text-left" aria-label="Page alignment">
        <thead className="text-muted"><tr><th className="py-1 font-medium">Page</th><th className="font-medium">Alignment</th>
          <th className="font-medium">Similarity</th><th className="font-medium">Text</th></tr></thead>
        <tbody>
          {pages.map((p) => (
            <tr key={p.test_page} className="border-t border-line">
              <td className="py-1 tabular">{p.test_page}</td>
              <td>{p.alignment}</td>
              <td className="tabular">{p.page_ssim.toFixed(3)}</td>
              <td>{p.text_compared ? (p.test_text_method === "ocr" ? "compared (OCR)" : "compared") : "pixels only"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>
        {VLM_STATUS[detail.vlm_status]}
        {detail.vlm_model ? <> (<Mono>{detail.vlm_model}</Mono>)</> : null}
        {vlm ? `: ${String(vlm["calls"])} calls, ${String(vlm["seconds"])} s, ${String(vlm["boxes_rejected"])} model boxes rejected, ${(vlm["proposals_rejected"] as unknown[] | undefined)?.length ?? 0} proposals without pixel evidence` : null}
        {typeof s["vlm_note"] === "string" ? <span className="block text-muted">{s["vlm_note"]}</span> : null}
      </p>
      <p className="text-muted">{detail.limitation}</p>
    </div>
  );
}

export function ComparisonView({ comparisonId, docs }: { comparisonId: string; docs: Map<string, PaneDoc> }) {
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);
  const detail = useQuery({
    queryKey: ["comparison", comparisonId],
    queryFn: () => api.comparison(comparisonId),
    refetchInterval: (q) => {
      const d = q.state.data;
      return d && (ACTIVE_STATUSES.has(d.status) || d.exports.some((e) => e.status === "queued")) ? 2000 : false;
    },
  });
  if (detail.isPending) return <Skeleton className="h-[60vh]" />;
  if (detail.isError) return <Card><ErrorState error={detail.error} onRetry={() => void detail.refetch()} /></Card>;
  const d = detail.data;
  const status = COMPARISON_STATUS[d.status];
  const original = docs.get(d.original_document_id);
  const test = docs.get(d.test_document_id);
  const select = (f: ComparisonFindingOut) => {
    setSelected(f.id);
    const target = f.test_page ?? f.original_page;
    if (target) setPage(target);
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardTitle action={<Badge tone={status.tone}>{status.label}</Badge>}>
          {d.original_filename} <span className="text-muted">vs</span> {d.test_filename}
        </CardTitle>
        {d.status === "completed" ? (
          <p className="text-sm text-muted">
            {d.findings.length} difference{d.findings.length === 1 ? "" : "s"} found, {d.findings_unreviewed} not reviewed.
            {" "}{VLM_STATUS[d.vlm_status]}.
          </p>
        ) : <Progress detail={d} />}
      </Card>
      {d.status === "completed" && original && test ? (
        <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_380px]">
          <Card className="min-w-0 p-3">
            <SyncedViewer original={original} test={test} findings={d.findings} page={page} onPage={setPage}
                          selected={selected}
                          onSelect={(id) => { const f = d.findings.find((x) => x.id === id); if (f) select(f); }} />
          </Card>
          <div className="space-y-4">
            <Card>
              <CardTitle>Differences</CardTitle>
              <FindingsPanel comparisonId={d.id} findings={d.findings} selected={selected} onSelect={select} />
            </Card>
            <Card>
              <CardTitle>Downloads</CardTitle>
              <ExportsPanel comparisonId={d.id} exports={d.exports} />
            </Card>
            <Card>
              <CardTitle>How it was measured</CardTitle>
              <Summary detail={d} />
            </Card>
          </div>
        </div>
      ) : d.status === "completed" ? (
        <Card><p className="text-sm text-muted">One of the compared documents is no longer available in this investigation.</p></Card>
      ) : null}
    </div>
  );
}
