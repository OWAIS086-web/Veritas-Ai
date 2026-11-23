import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Link, useSearchParams } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { EmptyState, ErrorState } from "@/components/QueryState";
import { Badge, Card, Select, Skeleton } from "@/components/ui/primitives";
import { docTypeLabel } from "@/features/documents/labels";
import { ComparisonLab } from "@/features/forensics/comparison/ComparisonLab";
import { ForensicDocument } from "@/features/forensics/ForensicDocument";
import { anomalyLabel, RUN_STATUS } from "@/features/forensics/labels";
import { api } from "@/services/api";
import { usePermission } from "@/stores/auth";

const TABS = [
  { id: "documents", label: "Document forensics" },
  { id: "compare", label: "Comparison Lab" },
] as const;
type Tab = (typeof TABS)[number]["id"];

function Tabs({ tab, onTab }: { tab: Tab; onTab: (tab: Tab) => void }) {
  return (
    <div role="tablist" aria-label="Forensics Lab sections" className="mb-4 flex gap-1 border-b border-line">
      {TABS.map((t) => (
        <button key={t.id} type="button" role="tab" id={`tab-${t.id}`} aria-selected={tab === t.id}
                aria-controls={`panel-${t.id}`} onClick={() => onTab(t.id)}
                className={clsx("-mb-px border-b-2 px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-evidence",
                                tab === t.id ? "border-evidence text-ink" : "border-transparent text-muted hover:text-ink")}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function ForensicsPage() {
  const [params, setParams] = useSearchParams();
  const cases = useQuery({ queryKey: ["cases", "forensics-picker"], queryFn: () => api.cases({}) });
  const canCompare = usePermission("comparisons:read");
  const items = cases.data?.items ?? [];
  const caseId = params.get("case") ?? items[0]?.id ?? "";
  const tab: Tab = params.get("tab") === "compare" && canCompare ? "compare" : "documents";
  // Every change keeps the case and the tab; each tab keeps its own selection.
  const go = (next: Record<string, string>) =>
    setParams({ case: caseId, ...(tab === "compare" ? { tab } : {}), ...next });

  return (
    <div>
      <PageHeader
        title="Forensics Lab"
        subtitle="PDF structure, compression, version and stamp observations, and original-versus-test comparisons, for review. An anomaly or a difference is not a conclusion about the document."
        actions={items.length > 0 ? (
          <Select label="Investigation" hideLabel value={caseId} className="w-80"
                  onChange={(e) => setParams({ case: e.target.value, ...(tab === "compare" ? { tab } : {}) })}>
            {items.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
          </Select>
        ) : null}
      />
      {canCompare ? (
        <Tabs tab={tab} onTab={(t) => setParams({ ...(caseId ? { case: caseId } : {}), ...(t === "compare" ? { tab: t } : {}) })} />
      ) : null}
      {cases.isPending ? <Skeleton className="h-[60vh]" /> : cases.isError ? (
        <Card><ErrorState error={cases.error} onRetry={() => void cases.refetch()} /></Card>
      ) : !caseId ? (
        <Card>
          <EmptyState title="No investigations yet"
                      action={<Link to="/investigations/new" className="text-sm text-evidence hover:underline">Create an investigation</Link>}>
            Upload documents to an investigation; each processed PDF or image is analysed here.
          </EmptyState>
        </Card>
      ) : tab === "compare" ? (
        <div role="tabpanel" id="panel-compare" aria-labelledby="tab-compare">
          <ComparisonLab key={caseId} caseId={caseId} comparisonId={params.get("cmp")}
                         onSelect={(cmp) => go({ cmp })} />
        </div>
      ) : (
        <div role={canCompare ? "tabpanel" : undefined} id="panel-documents"
             aria-labelledby={canCompare ? "tab-documents" : undefined}>
          <CaseForensics key={caseId} caseId={caseId} documentId={params.get("doc")}
                         onSelect={(doc) => go({ doc })} />
        </div>
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
