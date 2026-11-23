import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Focus } from "lucide-react";
import { Link } from "react-router-dom";

import { ErrorState } from "@/components/QueryState";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardTitle, Mono, Skeleton } from "@/components/ui/primitives";
import { docTypeLabel } from "@/features/documents/labels";
import { categoryOf, EDGE_LABELS } from "@/features/graph/model";
import { api } from "@/services/api";
import type { EdgeEvidenceOut, GraphEdgeOut, GraphNodeOut } from "@/types/api";

function sourceLink(e: { document_id: string; extracted_field_id?: string | null }) {
  return `/documents/${e.document_id}${e.extracted_field_id ? `?field=${e.extracted_field_id}` : ""}`;
}

function where(e: { page_number?: number | null; location?: string | null }) {
  return e.page_number != null ? `page ${e.page_number}` : e.location ?? "location not recorded";
}

export function EdgeDetails({ edge, nodes }: { edge: GraphEdgeOut; nodes: Map<string, GraphNodeOut> }) {
  const evidence = useQuery({
    queryKey: ["relationship-evidence", edge.id],
    queryFn: () => api.relationshipEvidence(edge.id),
  });
  const from = nodes.get(edge.source)?.label ?? edge.source;
  const to = nodes.get(edge.target)?.label ?? edge.target;
  return (
    <Card>
      <CardTitle>Relationship</CardTitle>
      <p className="text-sm">
        <span className="font-medium">{from}</span>{" "}
        <Badge tone={edge.type === "CONTRADICTS" ? "danger" : "evidence"}>{EDGE_LABELS[edge.type] ?? edge.type}</Badge>{" "}
        <span className="font-medium">{to}</span>
      </p>
      {edge.finding_id ? (
        <p className="mt-2 text-xs">
          <Link to={`/findings/${edge.finding_id}`} className="text-evidence hover:underline">Open the finding</Link>
        </p>
      ) : null}
      <h3 className="mt-4 text-xs font-semibold uppercase tracking-[0.14em] text-muted">
        Evidence ({edge.evidence_ids.length})
      </h3>
      {evidence.isPending ? <Skeleton className="mt-2 h-20" /> : evidence.isError ? (
        <ErrorState error={evidence.error} onRetry={() => void evidence.refetch()} />
      ) : (
        <ul className="mt-2 space-y-2" aria-label="Relationship evidence">
          {evidence.data.map((e: EdgeEvidenceOut) => (
            <li key={e.id} className="rounded-lg border border-line p-2.5">
              <p className="text-xs text-muted">{docTypeLabel(e.doc_type)} · {e.document_filename}</p>
              <p className="mt-0.5 text-sm">{e.field_name.replace(/_/g, " ")}: <Mono className="text-ink">{e.value ?? "null"}</Mono></p>
              <Link to={sourceLink(e)} className="mt-1 inline-flex items-center gap-1 text-xs text-evidence hover:underline"
                    aria-label={`Open ${e.document_filename} at ${where(e)}`}>
                Open at {where(e)} <ExternalLink className="h-3 w-3" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function NodeDetails({ node, onFocus, focused }: {
  node: GraphNodeOut; onFocus: () => void; focused: boolean;
}) {
  const entity = useQuery({
    queryKey: ["entity", node.id],
    queryFn: () => api.entity(node.id),
    enabled: node.kind === "entity",
  });
  return (
    <Card>
      <CardTitle action={
        <Button size="sm" variant="ghost" icon={<Focus className="h-3.5 w-3.5" />} onClick={onFocus}>
          {focused ? "Show all" : "Show neighbours"}
        </Button>
      }>
        {categoryOf(node)}
      </CardTitle>
      <p className="text-sm font-medium">{node.label}</p>
      {node.kind === "document" ? (
        <Link to={`/documents/${node.id}`} className="mt-2 inline-flex items-center gap-1 text-xs text-evidence hover:underline">
          Open document <ExternalLink className="h-3 w-3" aria-hidden />
        </Link>
      ) : null}
      {node.kind === "finding" ? (
        <Link to={`/findings/${node.id}`} className="mt-2 inline-flex items-center gap-1 text-xs text-evidence hover:underline">
          Open finding <ExternalLink className="h-3 w-3" aria-hidden />
        </Link>
      ) : null}
      {node.kind === "entity" ? (
        entity.isPending ? <Skeleton className="mt-3 h-20" /> : entity.isError ? (
          <ErrorState error={entity.error} onRetry={() => void entity.refetch()} />
        ) : (
          <>
            <p className="mt-1 text-xs text-muted">
              {entity.data.status === "possible_duplicate" ? "Possible duplicate of a similar name · " : ""}
              confidence {entity.data.confidence ?? "not measured"} · {entity.data.mention_count} mentions
            </p>
            <ul className="mt-3 space-y-2" aria-label="Entity mentions">
              {(entity.data.mentions ?? []).map((m) => (
                <li key={m.id} className="rounded-lg border border-line p-2.5">
                  <p className="text-xs text-muted">{m.document_filename} · {m.field_name.replace(/_/g, " ")}</p>
                  <p className="mt-0.5 text-sm"><Mono className="text-ink">{m.value ?? "null"}</Mono></p>
                  <Link to={sourceLink(m)} className="mt-1 inline-flex items-center gap-1 text-xs text-evidence hover:underline"
                        aria-label={`Open ${m.document_filename} at ${where(m)}`}>
                    Open at {where(m)} <ExternalLink className="h-3 w-3" aria-hidden />
                  </Link>
                </li>
              ))}
            </ul>
          </>
        )
      ) : null}
    </Card>
  );
}
