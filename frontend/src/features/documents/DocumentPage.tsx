import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { ErrorState } from "@/components/QueryState";
import { Card, Mono, Skeleton } from "@/components/ui/primitives";
import { docTypeLabel, formatBytes, STAGE_LABELS } from "@/features/documents/labels";
import { StatusBadge } from "@/features/documents/StatusBadge";
import { DocumentViewer } from "@/features/viewer/DocumentViewer";
import { api } from "@/services/api";

export function DocumentPage() {
  const { documentId = "" } = useParams();
  const [params] = useSearchParams();
  const doc = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => api.document(documentId),
    refetchInterval: (q) => (q.state.data && ["uploaded", "processing"].includes(q.state.data.status) ? 4000 : false),
  });

  if (doc.isPending) return <Skeleton className="h-[70vh]" />;
  if (doc.isError) return <Card><ErrorState error={doc.error} onRetry={() => void doc.refetch()} /></Card>;
  const d = doc.data;
  return (
    <div>
      <PageHeader
        title={d.original_filename}
        subtitle={<span className="flex flex-wrap items-center gap-2">
          <StatusBadge status={d.status} stage={d.current_stage} /> {docTypeLabel(d.doc_type)}
          {d.classification_confidence ? <span className="text-xs">(rule match {d.classification_confidence})</span> : null}
          · <Link to={`/investigations/${d.case_id}`} className="text-evidence hover:underline">Open case</Link>
        </span>}
      />
      <dl className="mb-6 grid gap-3 text-xs sm:grid-cols-2 xl:grid-cols-4">
        <Meta label="SHA-256 of the original"><Mono className="break-all">{d.sha256}</Mono></Meta>
        <Meta label="Detected type">{d.mime_type} <span className="text-muted">({d.detection_reason})</span></Meta>
        <Meta label="Size · pages · language">{formatBytes(d.size_bytes)} · {d.page_count ?? "—"} · {d.language ?? "unknown"}</Meta>
        <Meta label="Stages">
          {(d.stages ?? []).map((s) => (
            <span key={s.stage} className="mr-2">{STAGE_LABELS[s.stage] ?? s.stage}: {s.status}
              {typeof s.metrics.duration_ms === "number" ? <Mono className="text-muted"> {Math.round(s.metrics.duration_ms)} ms</Mono> : null}
            </span>
          ))}
        </Meta>
      </dl>
      {d.error ? <p role="alert" className="mb-4 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">{d.error}</p> : null}
      <DocumentViewer key={`${d.id}-${d.status}`} doc={d} initialFieldId={params.get("field")} />
    </div>
  );
}

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="panel p-3">
      <dt className="text-muted">{label}</dt>
      <dd className="mt-1 text-ink">{children}</dd>
    </div>
  );
}
