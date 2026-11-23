import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { EmptyState, ErrorState } from "@/components/QueryState";
import { Badge, Card, Mono, Select, Skeleton } from "@/components/ui/primitives";
import { SeverityBadge } from "@/features/findings/badges";
import { fieldLabel } from "@/features/documents/labels";
import type { OverlayBox } from "@/features/viewer/overlay";
import { PageView } from "@/features/viewer/PageView";
import { api } from "@/services/api";
import type { EvidenceOut } from "@/types/api";

type Side = "left" | "right";
const ROLE_TONE: Record<string, OverlayBox["tone"]> = { supporting: "evidence", conflicting: "danger", context: "muted" };
const ROLE_LABEL: Record<string, string> = { supporting: "Supporting", conflicting: "Conflicting", context: "Context" };

/** "docId:page" ⇄ { doc, page } in the URL, so a comparison can be shared and reloaded. */
function parsePane(value: string | null): { doc: string; page: number } | null {
  if (!value) return null;
  const [doc, page] = value.split(":");
  return doc ? { doc, page: Math.max(1, Number(page) || 1) } : null;
}

export function EvidenceExplorerPage() {
  const [params, setParams] = useSearchParams();
  const findingId = params.get("finding");
  const findings = useQuery({ queryKey: ["findings", "explorer-picker"], queryFn: () => api.findings({}) });

  return (
    <div>
      <PageHeader
        title="Evidence Explorer"
        subtitle="Compare the documents behind a finding side by side, each opened at the cited page with the value highlighted."
        actions={findings.data && findings.data.items.length > 0 ? (
          <Select label="Finding" hideLabel value={findingId ?? ""} className="w-96"
                  onChange={(e) => setParams({ finding: e.target.value })}>
            <option value="">Choose a finding</option>
            {findings.data.items.map((f) => <option key={f.id} value={f.id}>{f.case_title}: {f.title}</option>)}
          </Select>
        ) : null}
      />
      {findings.isPending ? <Skeleton className="h-[60vh]" /> : findings.isError ? (
        <Card><ErrorState error={findings.error} onRetry={() => void findings.refetch()} /></Card>
      ) : !findingId ? (
        <Card>
          <EmptyState title={findings.data.items.length ? "Choose a finding" : "No findings yet"}
                      action={<Link to="/findings" className="text-sm text-evidence hover:underline">Open the Findings Center</Link>}>
            Findings are created when the documents of an investigation are compared. Pick one to see its evidence.
          </EmptyState>
        </Card>
      ) : (
        <Compare key={findingId} findingId={findingId} />
      )}
    </div>
  );
}

function Compare({ findingId }: { findingId: string }) {
  const [params, setParams] = useSearchParams();
  const finding = useQuery({ queryKey: ["finding", findingId], queryFn: () => api.finding(findingId) });
  const evidence = useMemo(() => finding.data?.evidence ?? [], [finding.data]);

  // One entry per document, opened at the page of its first evidence item.
  const docs = useMemo(() => {
    const seen = new Map<string, EvidenceOut>();
    for (const e of evidence) if (!seen.has(e.document_id)) seen.set(e.document_id, e);
    return [...seen.values()];
  }, [evidence]);

  if (finding.isPending) return <Skeleton className="h-[60vh]" />;
  if (finding.isError) return <Card><ErrorState error={finding.error} onRetry={() => void finding.refetch()} /></Card>;
  const f = finding.data;
  if (docs.length === 0) {
    return (
      <Card>
        <EmptyState title="This finding has no evidence documents"
                    action={<Link to={`/findings/${f.id}`} className="text-sm text-evidence hover:underline">Open the finding</Link>}>
          It is based on an absence (for example a missing document), so there is nothing to highlight.
        </EmptyState>
      </Card>
    );
  }
  // Default comparison: a supporting document (or the first one) against a conflicting
  // document; failing that, against one whose cited value differs (for an amount mismatch
  // every value conflicts, so the useful comparison is 48,000 against 68,000).
  const supporting = docs.find((d) => d.role === "supporting") ?? docs[0];
  const others = docs.filter((d) => d.document_id !== supporting?.document_id);
  const conflicting = (supporting?.role === "supporting" ? others.find((d) => d.role === "conflicting") : undefined)
    ?? others.find((d) => d.value !== supporting?.value) ?? others[0] ?? supporting;
  const pane = (side: Side) => {
    const fallback = side === "left" ? supporting : conflicting;
    return parsePane(params.get(side)) ?? { doc: fallback?.document_id ?? "", page: fallback?.page_number ?? 1 };
  };
  const setPane = (side: Side, doc: string, page: number) => {
    const next = new URLSearchParams(params);
    next.set(side, `${doc}:${page}`);
    setParams(next, { replace: true });
  };

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-center gap-2">
          <SeverityBadge severity={f.severity} />
          <h2 className="text-base font-medium">{f.title}</h2>
          <Link to={`/findings/${f.id}`} className="ml-auto text-xs text-evidence hover:underline">Review this finding</Link>
        </div>
        <p className="mt-2 text-sm text-muted">{f.explanation}</p>
        <p className="mt-2 flex flex-wrap items-center gap-3 text-xs" aria-label="Highlight legend">
          <span className="inline-flex items-center gap-1"><span className="h-3 w-4 rounded-sm border border-evidence bg-evidence/10" aria-hidden />Supporting value</span>
          <span className="inline-flex items-center gap-1"><span className="h-3 w-4 rounded-sm border border-danger bg-danger/10" aria-hidden />Conflicting value</span>
        </p>
      </Card>
      <div className="grid gap-4 xl:grid-cols-2">
        {(["left", "right"] as const).map((side) => {
          const p = pane(side);
          return (
            <EvidencePane key={side} side={side} docs={docs} evidence={evidence} docId={p.doc} page={p.page}
                          onChange={(doc, page) => setPane(side, doc, page)} />
          );
        })}
      </div>
    </div>
  );
}

function EvidencePane({ side, docs, evidence, docId, page, onChange }: {
  side: Side;
  docs: EvidenceOut[];
  evidence: EvidenceOut[];
  docId: string;
  page: number;
  onChange: (doc: string, page: number) => void;
}) {
  const doc = useQuery({ queryKey: ["document", docId], queryFn: () => api.document(docId), enabled: !!docId });
  const items = evidence.filter((e) => e.document_id === docId);
  const boxes: OverlayBox[] = items
    .filter((e) => e.bbox && e.page_number === page)
    .map((e) => ({
      id: e.id,
      bbox: e.bbox as number[],
      label: `${ROLE_LABEL[e.role] ?? e.role}: ${fieldLabel(e.field_name)} ${e.value ?? ""}`.trim(),
      tone: ROLE_TONE[e.role] ?? "muted",
      active: true,
    }));
  const located = items.find((e) => e.location && !e.bbox);
  const label = side === "left" ? "Left document" : "Right document";

  return (
    <Card className="min-w-0 p-0">
      <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
        <Select label={label} hideLabel value={docId} className="w-72"
                onChange={(e) => {
                  const first = evidence.find((x) => x.document_id === e.target.value);
                  onChange(e.target.value, first?.page_number ?? 1);
                }}>
          {docs.map((d) => <option key={d.document_id} value={d.document_id}>{d.document_filename}</option>)}
        </Select>
        <ul className="flex flex-wrap gap-1" aria-label={`Evidence in the ${side} document`}>
          {items.map((e) => (
            <li key={e.id}>
              <button type="button" onClick={() => onChange(docId, e.page_number ?? 1)}
                      className="rounded-md border border-line px-2 py-0.5 text-xs hover:bg-elevated">
                <Badge tone={e.role === "conflicting" ? "danger" : e.role === "supporting" ? "evidence" : "neutral"}>
                  {ROLE_LABEL[e.role] ?? e.role}
                </Badge>{" "}
                {fieldLabel(e.field_name)} <Mono>{e.value}</Mono> · page {e.page_number ?? "n/a"}
              </button>
            </li>
          ))}
        </ul>
      </div>
      {doc.isPending ? <Skeleton className="h-[60vh]" /> : doc.isError ? (
        <ErrorState error={doc.error} onRetry={() => void doc.refetch()} />
      ) : (
        <PageView documentId={docId} mimeType={doc.data.mime_type} filename={doc.data.original_filename}
                  page={page} onPage={(p) => onChange(docId, p)} boxes={boxes}
                  activeLocation={located?.location ?? null} knownPages={doc.data.page_count} />
      )}
    </Card>
  );
}
