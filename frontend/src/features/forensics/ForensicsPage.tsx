import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Link, useSearchParams } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { EmptyState, ErrorState } from "@/components/QueryState";
import { Badge, Card, Select, Skeleton } from "@/components/ui/primitives";
import { docTypeLabel } from "@/features/documents/labels";
import { ForensicDocument } from "@/features/forensics/ForensicDocument";
import { anomalyLabel, RUN_STATUS } from "@/features/forensics/labels";
import { api } from "@/services/api";

export function ForensicsPage() {
  const [params, setParams] = useSearchParams();
  const cases = useQuery({ queryKey: ["cases", "forensics-picker"], queryFn: () => api.cases({}) });
  const items = cases.data?.items ?? [];
  const caseId = params.get("case") ?? items[0]?.id ?? "";

  return (
    <div>
      <PageHeader
        title="Forensics Lab"
        subtitle="PDF structure, compression, version and stamp observations for review. An anomaly is not a conclusion about the document."
        actions={items.length > 0 ? (
          <Select label="Investigation" hideLabel value={caseId} className="w-80"
                  onChange={(e) => setParams({ case: e.target.value })}>
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
            Upload documents to an investigation; each processed PDF or image is analysed here.
          </EmptyState>
        </Card>
      ) : (
        <CaseForensics key={caseId} caseId={caseId} documentId={params.get("doc")}
                       onSelect={(doc) => setParams({ case: caseId, doc })} />
      )}
    </div>
  );
}

function CaseForensics({ caseId, documentId, onSelect }: {
  caseId: string;
  documentId: string | null;
  onSelect: (doc: string) => void;
}) {
  const summary = useQuery({ queryKey: ["case-forensics", caseId], queryFn: () => api.caseForensics(caseId) });

  if (summary.isPending) return <Skeleton className="h-[60vh]" />;
  if (summary.isError) {
    return <Card><ErrorState error={summary.error} onRetry={() => void summary.refetch()} /></Card>;
  }
  if (summary.data.length === 0) {
    return (
      <Card>
        <EmptyState title="No documents in this investigation"
                    action={<Link to={`/investigations/${caseId}`} className="text-sm text-evidence hover:underline">Upload documents</Link>}>
          Forensic analysis runs on each document as the last processing stage.
        </EmptyState>
      </Card>
    );
  }
  const current = summary.data.find((d) => d.document_id === documentId) ?? summary.data[0];

  return (
    <div className="space-y-4">
      <Card className="overflow-x-auto p-0">
        <table className="w-full text-left text-sm" aria-label="Documents by forensic review priority">
          <thead className="border-b border-line text-xs uppercase tracking-wider text-muted">
            <tr>
              <th scope="col" className="px-4 py-2 font-medium">Document</th>
              <th scope="col" className="px-4 py-2 font-medium">Status</th>
              <th scope="col" className="px-4 py-2 font-medium">Medium</th>
              <th scope="col" className="px-4 py-2 font-medium">Low</th>
              <th scope="col" className="px-4 py-2 font-medium">Anomaly types</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {summary.data.map((d) => {
              const status = d.status ? RUN_STATUS[d.status] : undefined;
              const active = current?.document_id === d.document_id;
              return (
                <tr key={d.document_id} className={clsx(active && "bg-elevated")}>
                  <td className="px-4 py-2">
                    <button type="button" onClick={() => onSelect(d.document_id)} aria-current={active ? "true" : undefined}
                            className="text-left hover:text-evidence">
                      {d.filename}
                    </button>
                    <p className="text-[11px] text-muted">{docTypeLabel(d.doc_type)}</p>
                  </td>
                  <td className="px-4 py-2">
                    {status ? <Badge tone={status.tone}>{status.label}</Badge> : <Badge>Not analysed</Badge>}
                  </td>
                  <td className="px-4 py-2 tabular">{d.medium}</td>
                  <td className="px-4 py-2 tabular">{d.low}</td>
                  <td className="px-4 py-2 text-xs text-muted">
                    {(d.types ?? []).length ? (d.types ?? []).map(anomalyLabel).join(", ") : "None"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
      {current ? <ForensicDocument key={current.document_id} summary={current} /> : null}
    </div>
  );
}
