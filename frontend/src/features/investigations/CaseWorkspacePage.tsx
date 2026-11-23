import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { ExternalLink, Play, RotateCw } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";

import { Dropzone } from "@/components/Dropzone";
import { PageHeader } from "@/components/PageHeader";
import { EmptyState, ErrorState } from "@/components/QueryState";
import { Button } from "@/components/ui/Button";
import { Card, CardTitle, Mono, Skeleton } from "@/components/ui/primitives";
import { docTypeLabel, STAGE_LABELS } from "@/features/documents/labels";
import { StatusBadge } from "@/features/documents/StatusBadge";
import { useJobStream } from "@/features/documents/useJobStream";
import { CaseFindingsPanel } from "@/features/findings/CaseFindingsPanel";
import { PriorityBadge } from "@/features/investigations/InvestigationsPage";
import { DocumentViewer } from "@/features/viewer/DocumentViewer";
import { api, ApiError } from "@/services/api";
import { usePermission } from "@/stores/auth";
import { toast } from "@/stores/toast";
import type { DocumentOut } from "@/types/api";

const ACTIVE = new Set(["uploaded", "processing"]);

export function CaseWorkspacePage() {
  const { caseId = "" } = useParams();
  const location = useLocation();
  const qc = useQueryClient();
  const canUpload = usePermission("documents:upload");
  const canProcess = usePermission("documents:process");
  const [jobId, setJobId] = useState<string | null>((location.state as { jobId?: string } | null)?.jobId ?? null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const caseQuery = useQuery({ queryKey: ["case", caseId], queryFn: () => api.caseById(caseId) });
  const docs = useQuery({
    queryKey: ["case-documents", caseId],
    queryFn: () => api.caseDocuments(caseId),
    // Status is persisted server-side: polling keeps it current after a reload, SSE makes it live.
    refetchInterval: (q) => (q.state.data?.some((d) => ACTIVE.has(d.status)) ? 4000 : false),
  });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["case-documents", caseId] });
    void qc.invalidateQueries({ queryKey: ["case", caseId] });
  };
  const stream = useJobStream(jobId, (e) => {
    if (e.type.startsWith("stage_") || e.type.startsWith("document_") || e.type === "succeeded") refresh();
    if (e.type.startsWith("comparison_") || e.type === "succeeded") {
      void qc.invalidateQueries({ queryKey: ["case-findings", caseId] });
    }
  });

  useEffect(() => {
    if (!selectedId && docs.data?.length) setSelectedId(docs.data[0]?.id ?? null);
  }, [docs.data, selectedId]);

  const upload = useMutation({
    mutationFn: (files: File[]) => api.uploadDocuments(caseId, files),
    onSuccess: (res) => {
      const accepted = res.results.filter((r) => r.status === "accepted").length;
      const other = res.results.filter((r) => r.status !== "accepted");
      if (res.job_id) setJobId(res.job_id);
      refresh();
      toast.success(`${accepted} document(s) queued`,
        other.length ? other.map((r) => `${r.filename}: ${r.status}${r.reason ? ` (${r.reason})` : ""}`).join("; ") : undefined);
    },
    onError: (err) => toast.error("Upload failed", err instanceof ApiError ? err.detail : undefined),
  });
  const process = useMutation({
    mutationFn: () => api.processCase(caseId),
    onSuccess: (res) => {
      if (res.job_id) setJobId(res.job_id);
      refresh();
      toast.info(res.job_id ? `${res.document_ids.length} document(s) queued` : "Nothing to process", res.job_id ? undefined : "Every document is completed or already processing.");
    },
    onError: (err) => toast.error("Could not queue processing", err instanceof ApiError ? err.detail : undefined),
  });
  const retry = useMutation({
    mutationFn: (id: string) => api.retryDocument(id),
    onSuccess: (job) => { setJobId(job.id); refresh(); toast.info("Retry queued", "Processing resumes from the failed stage."); },
    onError: (err) => toast.error("Retry failed", err instanceof ApiError ? err.detail : undefined),
  });

  if (caseQuery.isError) return <Card><ErrorState error={caseQuery.error} onRetry={() => void caseQuery.refetch()} /></Card>;
  const c = caseQuery.data;
  const selected = docs.data?.find((d) => d.id === selectedId) ?? null;
  const pending = docs.data?.some((d) => d.status === "uploaded" || d.status === "failed");

  return (
    <div>
      <PageHeader
        title={c?.title ?? "Investigation"}
        subtitle={c ? <>{c.objective || "No objective recorded."} · <PriorityBadge priority={c.priority} /></> : undefined}
        actions={canProcess && pending ? (
          <Button variant="secondary" icon={<Play className="h-4 w-4" />} loading={process.isPending}
                  onClick={() => process.mutate()}>Process pending</Button>
        ) : null}
      />
      {jobId && stream.status && stream.status !== "succeeded" ? (
        <div role="status" className="mb-4 flex items-center gap-3 rounded-lg border border-evidence/30 bg-evidence/5 px-4 py-2 text-sm">
          <span>Job <Mono>{jobId.slice(0, 8)}</Mono>: {stream.status}</span>
          <div className="h-1.5 flex-1 overflow-hidden rounded bg-elevated" aria-hidden>
            <div className="h-full bg-evidence transition-all" style={{ width: `${stream.progress}%` }} />
          </div>
          <Mono>{stream.progress}%</Mono>
        </div>
      ) : null}
      {c ? (
        <CaseFindingsPanel caseItem={c} onJob={setJobId}
                           busy={Boolean(jobId && stream.status && !["succeeded", "failed"].includes(stream.status))} />
      ) : null}
      <div className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
        <div className="space-y-4">
          <Card className="p-3">
            <CardTitle>Documents</CardTitle>
            {docs.isPending ? <Skeleton className="h-40" /> : docs.isError ? (
              <ErrorState error={docs.error} onRetry={() => void docs.refetch()} />
            ) : docs.data.length === 0 ? (
              <EmptyState title="No documents yet">Upload the case documents below.</EmptyState>
            ) : (
              <ul className="space-y-1" aria-label="Case documents">
                {docs.data.map((d) => (
                  <DocumentRow key={d.id} doc={d} active={d.id === selectedId} onSelect={() => setSelectedId(d.id)}
                               onRetry={canProcess ? () => retry.mutate(d.id) : undefined} retrying={retry.isPending} />
                ))}
              </ul>
            )}
          </Card>
          {canUpload ? <Dropzone compact onFiles={(files) => upload.mutate(files)} disabled={upload.isPending} /> : null}
        </div>
        <div className="min-w-0">
          {selected ? (
            <>
              <div className="mb-3 flex flex-wrap items-center gap-3">
                <h2 className="text-base font-semibold">{selected.original_filename}</h2>
                <StatusBadge status={selected.status} stage={selected.current_stage} />
                <span className="text-xs text-muted">{docTypeLabel(selected.doc_type)}</span>
                <Link to={`/documents/${selected.id}`} className="ml-auto inline-flex items-center gap-1 text-xs text-evidence hover:underline">
                  Open full view <ExternalLink className="h-3 w-3" aria-hidden />
                </Link>
              </div>
              <DocumentViewer key={`${selected.id}-${selected.status}`} doc={selected} />
            </>
          ) : (
            <Card><EmptyState title="Select a document">Its pages and extracted fields appear here.</EmptyState></Card>
          )}
        </div>
      </div>
    </div>
  );
}

function DocumentRow({ doc, active, onSelect, onRetry, retrying }: {
  doc: DocumentOut; active: boolean; onSelect: () => void; onRetry?: () => void; retrying: boolean;
}) {
  return (
    <li className={clsx("rounded-lg border", active ? "border-evidence/50 bg-elevated" : "border-transparent hover:bg-elevated/60")}>
      <button type="button" onClick={onSelect} aria-current={active || undefined} className="w-full p-2.5 text-left">
        <p className="truncate text-sm font-medium">{doc.original_filename}</p>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <StatusBadge status={doc.status} stage={doc.current_stage ? STAGE_LABELS[doc.current_stage] : null} />
          <span className="text-[11px] text-muted">{docTypeLabel(doc.doc_type)}</span>
        </div>
        <ol className="mt-2 flex gap-1" aria-label="Stages">
          {(doc.stages ?? []).map((s) => (
            <li key={s.stage} title={`${STAGE_LABELS[s.stage] ?? s.stage}: ${s.status}${s.error ? ` (${s.error})` : ""}`}
                className={clsx("h-1 flex-1 rounded", s.status === "succeeded" ? "bg-primary" : s.status === "failed" ? "bg-danger" : s.status === "running" ? "animate-pulse bg-evidence" : "bg-elevated")}>
              <span className="sr-only">{STAGE_LABELS[s.stage] ?? s.stage}: {s.status}</span>
            </li>
          ))}
        </ol>
      </button>
      {doc.status === "failed" ? (
        <div className="px-2.5 pb-2.5">
          <p className="break-words text-[11px] text-danger">{doc.error}</p>
          {onRetry ? <Button size="sm" variant="secondary" className="mt-2" loading={retrying} icon={<RotateCw className="h-3.5 w-3.5" />} onClick={onRetry}>Retry</Button> : null}
        </div>
      ) : null}
    </li>
  );
}
