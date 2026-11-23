import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { EmptyState, ErrorState } from "@/components/QueryState";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardTitle, Mono, Select, Skeleton } from "@/components/ui/primitives";
import { startDownload } from "@/features/reports/download";
import { ReportPreview, type ReportModelView } from "@/features/reports/ReportPreview";
import { api, ApiError } from "@/services/api";
import { usePermission } from "@/stores/auth";
import { toast } from "@/stores/toast";
import type { ReportOut } from "@/types/api";

const FORMATS = [
  { value: "pdf", label: "PDF" },
  { value: "docx", label: "Word (DOCX)" },
  { value: "xlsx", label: "Excel (XLSX)" },
  { value: "json", label: "JSON" },
];
const STATUS_TONE: Record<string, "neutral" | "evidence" | "primary" | "danger"> = {
  queued: "neutral", running: "evidence", completed: "primary", failed: "danger",
};

export function ReportsPage() {
  const [params, setParams] = useSearchParams();
  const cases = useQuery({ queryKey: ["cases", "reports-picker"], queryFn: () => api.cases({}) });
  const items = cases.data?.items ?? [];
  const caseId = params.get("case") ?? items[0]?.id ?? "";

  return (
    <div>
      <PageHeader
        title="Reports"
        subtitle="Cited investigation reports in PDF, DOCX, XLSX and JSON. Every citation is re-checked against the records before export."
        actions={items.length > 0 ? (
          <Select label="Report case" hideLabel value={caseId} className="w-80" onChange={(e) => setParams({ case: e.target.value })}>
            {items.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
          </Select>
        ) : null}
      />
      {cases.isPending ? <Skeleton className="h-[60vh]" /> : cases.isError ? (
        <Card><ErrorState error={cases.error} onRetry={() => void cases.refetch()} /></Card>
      ) : !caseId ? (
        <Card>
          <EmptyState title="No investigations yet"
                      action={<Link to="/investigations/new" className="text-sm text-evidence hover:underline">Create an investigation</Link>}>
            Reports are built from a case's processed documents and findings.
          </EmptyState>
        </Card>
      ) : (
        <CaseReports key={caseId} caseId={caseId} selected={params.get("report")}
                     onSelect={(report) => setParams({ case: caseId, report })} />
      )}
    </div>
  );
}

function CaseReports({ caseId, selected, onSelect }: { caseId: string; selected: string | null; onSelect: (id: string) => void }) {
  const qc = useQueryClient();
  const canCreate = usePermission("reports:create");
  const [format, setFormat] = useState("pdf");
  const [investigation, setInvestigation] = useState("");
  const history = useQuery({
    queryKey: ["case-reports", caseId],
    queryFn: () => api.caseReports(caseId),
    // Poll while a report is being generated.
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === "queued" || r.status === "running") ? 2000 : false),
  });
  const investigations = useQuery({ queryKey: ["case-investigations", caseId], queryFn: () => api.caseInvestigations(caseId) });
  const approved = (investigations.data ?? []).filter((i) => i.status === "completed" && i.approved_at);
  const create = useMutation({
    mutationFn: () => api.createReport(caseId, format, investigation || null),
    onSuccess: (r) => {
      toast.success("Report requested", "It is generated and verified in the background.");
      void qc.invalidateQueries({ queryKey: ["case-reports", caseId] });
      onSelect(r.id);
    },
    onError: (err) => toast.error("Could not request the report", err instanceof ApiError ? err.detail : undefined),
  });

  if (history.isPending) return <Skeleton className="h-[60vh]" />;
  if (history.isError) return <Card><ErrorState error={history.error} onRetry={() => void history.refetch()} /></Card>;
  const current = history.data.find((r) => r.id === selected) ?? history.data[0];

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
        <Card>
          <CardTitle>Generate a report</CardTitle>
          {!canCreate ? <p className="text-sm text-muted">Your role can read reports but not generate them.</p> : (
            <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
              <Select label="Format" value={format} onChange={(e) => setFormat(e.target.value)}>
                {FORMATS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
              </Select>
              <Select label="Include an investigation" value={investigation} onChange={(e) => setInvestigation(e.target.value)}>
                <option value="">None (findings and evidence only)</option>
                {approved.map((i) => <option key={i.id} value={i.id}>Approved {new Date(i.approved_at as string).toLocaleString()}</option>)}
              </Select>
              <p className="text-xs text-muted">Only approved, completed investigations can be included.</p>
              <Button type="submit" loading={create.isPending}>Generate report</Button>
            </form>
          )}
        </Card>
        <Card className="overflow-x-auto p-0">
          <div className="p-5 pb-0"><CardTitle>History</CardTitle></div>
          {history.data.length === 0 ? <p className="px-5 pb-5 text-sm text-muted">No report has been generated for this case yet.</p> : (
            <table className="w-full text-left text-sm" aria-label="Report history">
              <thead className="border-b border-line text-xs uppercase tracking-wider text-muted">
                <tr>
                  <th scope="col" className="px-4 py-2 font-medium">Created</th>
                  <th scope="col" className="px-4 py-2 font-medium">Format</th>
                  <th scope="col" className="px-4 py-2 font-medium">Status</th>
                  <th scope="col" className="px-4 py-2 font-medium">Findings not yet reviewed</th>
                  <th scope="col" className="px-4 py-2 font-medium">By</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {history.data.map((r) => (
                  <tr key={r.id} className={current?.id === r.id ? "bg-elevated" : undefined}>
                    <td className="px-4 py-2">
                      <button type="button" onClick={() => onSelect(r.id)} className="hover:text-evidence"
                              aria-current={current?.id === r.id ? "true" : undefined}>
                        {new Date(r.created_at).toLocaleString()}
                      </button>
                    </td>
                    <td className="px-4 py-2 uppercase">{r.format}</td>
                    <td className="px-4 py-2"><Badge tone={STATUS_TONE[r.status] ?? "neutral"}>{r.status}</Badge></td>
                    <td className="px-4 py-2 tabular">{r.status === "completed" ? `${r.findings_not_reviewed} of ${r.findings_total}` : "–"}</td>
                    <td className="px-4 py-2 text-xs text-muted">{r.created_by_email ?? "former member"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
      {current ? <ReportView key={`${current.id}-${current.status}`} summary={current} /> : null}
    </div>
  );
}

function ReportView({ summary }: { summary: ReportOut }) {
  const detail = useQuery({
    queryKey: ["report", summary.id, summary.status],
    queryFn: () => api.report(summary.id),
    enabled: summary.status === "completed",
  });
  const download = useMutation({
    mutationFn: () => api.reportDownload(summary.id),
    onSuccess: (link) => startDownload(link.url),
    onError: (err) => toast.error("Download failed", err instanceof ApiError ? err.detail : undefined),
  });

  if (summary.status === "queued" || summary.status === "running") {
    return <Card><p className="text-sm text-muted" role="status">Generating and verifying the report…</p></Card>;
  }
  if (summary.status === "failed") {
    return (
      <Card>
        <CardTitle>The report was not exported</CardTitle>
        <p className="text-sm">Verification found references that don't resolve, so no file was stored:</p>
        <ul className="mt-2 list-disc space-y-1 pl-4 font-mono text-xs text-danger" role="alert">
          {(summary.error ?? "").split("; ").map((p) => <li key={p}>{p}</li>)}
        </ul>
      </Card>
    );
  }
  if (detail.isPending) return <Skeleton className="h-[50vh]" />;
  if (detail.isError) return <Card><ErrorState error={detail.error} onRetry={() => void detail.refetch()} /></Card>;
  const model = detail.data.model as unknown as ReportModelView | null;

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-center gap-3">
          <Button icon={<Download className="h-4 w-4" />} loading={download.isPending} onClick={() => download.mutate()}>
            Download {summary.format.toUpperCase()}
          </Button>
          <span className="text-xs text-muted">SHA-256 <Mono>{summary.sha256}</Mono></span>
          <span className="text-xs text-muted">{Math.round((summary.size_bytes ?? 0) / 1024)} KB</span>
        </div>
      </Card>
      {model ? <ReportPreview model={model} /> : null}
    </div>
  );
}
