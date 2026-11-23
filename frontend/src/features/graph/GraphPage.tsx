import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { RefreshCw, Search } from "lucide-react";
import { lazy, Suspense, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { EmptyState, ErrorState } from "@/components/QueryState";
import { Button } from "@/components/ui/Button";
import { Badge, Card, Select, Skeleton } from "@/components/ui/primitives";
import { EdgeDetails, NodeDetails } from "@/features/graph/DetailsPanel";
import { CATEGORIES, categoryOf, EDGE_LABELS, neighbourhood } from "@/features/graph/model";
import { api, ApiError } from "@/services/api";
import { usePermission } from "@/stores/auth";
import { toast } from "@/stores/toast";
import type { GraphNodeOut } from "@/types/api";

function categoryLabel(node: GraphNodeOut | undefined): string {
  return node ? categoryOf(node) : "";
}

const GraphCanvas = lazy(() => import("@/features/graph/GraphCanvas"));

export function GraphPage() {
  const [params, setParams] = useSearchParams();
  const cases = useQuery({ queryKey: ["cases", "graph-picker"], queryFn: () => api.cases({}) });
  const compared = (cases.data?.items ?? []).filter((c) => c.compared_at != null);
  const caseId = params.get("case") ?? compared[0]?.id ?? "";

  return (
    <div>
      <PageHeader
        title="Intelligence Graph"
        subtitle="Parties, shipments, documents and findings of a case. Every relationship links to the fields it is based on."
        actions={cases.data && (cases.data.items.length > 0) ? (
          <Select label="Investigation" hideLabel value={caseId} className="w-80"
                  onChange={(e) => setParams({ case: e.target.value })}>
            {cases.data.items.map((c) => (
              <option key={c.id} value={c.id}>{c.title}{c.compared_at ? "" : " (not compared yet)"}</option>
            ))}
          </Select>
        ) : null}
      />
      {cases.isPending ? <Skeleton className="h-[60vh]" /> : cases.isError ? (
        <Card><ErrorState error={cases.error} onRetry={() => void cases.refetch()} /></Card>
      ) : !caseId ? (
        <Card>
          <EmptyState title="No graph yet" action={<Link to="/investigations" className="text-sm text-evidence hover:underline">Open investigations</Link>}>
            The graph is built when the documents of an investigation have been processed and compared.
          </EmptyState>
        </Card>
      ) : (
        <CaseGraph key={caseId} caseId={caseId} />
      )}
    </div>
  );
}

function CaseGraph({ caseId }: { caseId: string }) {
  const qc = useQueryClient();
  const canRebuild = usePermission("graph:rebuild");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [types, setTypes] = useState<string[]>([]);
  const [view, setView] = useState<"graph" | "list">("graph");
  const [highlight, setHighlight] = useState(false);
  const [selected, setSelected] = useState<{ kind: "node" | "edge"; id: string } | null>(null);
  const [focus, setFocus] = useState<string | null>(null);

  const graph = useQuery({
    queryKey: ["case-graph", caseId, { types, query }],
    queryFn: () => api.caseGraph(caseId, { types: types.join(","), q: query }),
  });
  const rebuild = useMutation({
    mutationFn: () => api.rebuildGraph(caseId),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["case-graph", caseId] });
      toast.success("Graph rebuilt", `${r.entities} entities, ${r.relationships} relationships`);
    },
    onError: (err) => toast.error("Rebuild failed", err instanceof ApiError ? err.detail : undefined),
  });

  const data = graph.data;
  const shown = useMemo(() => {
    if (!data) return { nodes: [], edges: [] };
    if (!focus) return data;
    const keep = neighbourhood(focus, data.edges);
    return {
      nodes: data.nodes.filter((n) => keep.has(n.id)),
      edges: data.edges.filter((e) => keep.has(e.source) && keep.has(e.target)),
    };
  }, [data, focus]);
  const byId = useMemo(() => new Map((data?.nodes ?? []).map((n) => [n.id, n])), [data]);
  const selectedNode = selected?.kind === "node" ? byId.get(selected.id) : undefined;
  const selectedEdge = selected?.kind === "edge" ? data?.edges.find((e) => e.id === selected.id) : undefined;
  const contradictions = (data?.edges ?? []).filter((e) => e.type === "CONTRADICTS").length;

  const toggleType = (value: string) =>
    setTypes((t) => (t.includes(value) ? t.filter((x) => x !== value) : [...t, value]));

  return (
    <div>
      <form className="mb-4 flex flex-wrap items-center gap-3" onSubmit={(e) => { e.preventDefault(); setQuery(search.trim()); }}>
        <label className="relative">
          <span className="sr-only">Search the graph</span>
          <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted" aria-hidden />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search names and documents"
                 className="h-10 w-64 rounded-lg border border-line bg-bg/60 pl-9 pr-3 text-sm" />
        </label>
        <Button type="submit" size="sm" variant="secondary">Search</Button>
        <fieldset className="flex flex-wrap items-center gap-1.5" aria-label="Show node types">
          {CATEGORIES.map((c) => (
            <button key={c.value} type="button" aria-pressed={types.includes(c.value)} onClick={() => toggleType(c.value)}
                    className={clsx("rounded-md border px-2 py-1 text-xs", types.includes(c.value) ? "border-evidence/60 bg-evidence/10 text-evidence" : "border-line text-muted hover:text-ink")}>
              {c.label}
            </button>
          ))}
        </fieldset>
        <label className="flex items-center gap-2 text-xs text-muted">
          <input type="checkbox" checked={highlight} onChange={(e) => setHighlight(e.target.checked)} />
          Highlight contradictions ({contradictions})
        </label>
        <div className="ml-auto flex items-center gap-2">
          {data ? <Badge tone={data.source === "neo4j" ? "primary" : "warning"}>
            {data.source === "neo4j" ? "Neo4j" : "Postgres (graph sync pending or unavailable)"}
          </Badge> : null}
          <div className="flex rounded-lg border border-line" role="group" aria-label="View">
            {(["graph", "list"] as const).map((v) => (
              <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)}
                      className={clsx("px-3 py-1.5 text-xs capitalize", view === v ? "bg-elevated text-ink" : "text-muted")}>{v}</button>
            ))}
          </div>
          {canRebuild ? (
            <Button size="sm" variant="secondary" icon={<RefreshCw className="h-3.5 w-3.5" />} loading={rebuild.isPending}
                    onClick={() => rebuild.mutate()}>Rebuild</Button>
          ) : null}
        </div>
      </form>

      {graph.isPending ? <Skeleton className="h-[60vh]" /> : graph.isError ? (
        <Card><ErrorState error={graph.error} onRetry={() => void graph.refetch()} /></Card>
      ) : graph.data.total_nodes === 0 ? (
        <Card>
          <EmptyState title="This case has no graph yet"
                      action={<Link to={`/investigations/${caseId}`} className="text-sm text-evidence hover:underline">Open the investigation</Link>}>
            The graph is built when the case's documents are processed and compared.
          </EmptyState>
        </Card>
      ) : (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
          <div className="min-w-0">
            {shown.nodes.length === 0 ? (
              <Card><EmptyState title="Nothing matches">Change the search or the selected types.</EmptyState></Card>
            ) : view === "graph" ? (
              <div className="panel h-[68vh] overflow-hidden" aria-label="Graph canvas">
                <Suspense fallback={<Skeleton className="h-full" />}>
                  <GraphCanvas nodes={shown.nodes} edges={shown.edges} selected={selected?.id ?? null}
                               highlightContradictions={highlight}
                               onSelectNode={(id) => setSelected({ kind: "node", id })}
                               onSelectEdge={(id) => setSelected({ kind: "edge", id })} />
                </Suspense>
              </div>
            ) : (
              <Card className="overflow-x-auto p-0">
                <table className="w-full text-left text-sm" aria-label="Relationships">
                  <thead className="border-b border-line text-xs uppercase tracking-wider text-muted">
                    <tr>
                      <th scope="col" className="px-4 py-2 font-medium">From</th>
                      <th scope="col" className="px-4 py-2 font-medium">Relationship</th>
                      <th scope="col" className="px-4 py-2 font-medium">To</th>
                      <th scope="col" className="px-4 py-2 font-medium">Evidence</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {shown.edges.filter((e) => !highlight || e.type === "CONTRADICTS").map((e) => (
                      <tr key={e.id} className={clsx(selected?.id === e.id && "bg-elevated")}>
                        <td className="px-4 py-2">
                          <button type="button" className="hover:text-evidence" onClick={() => setSelected({ kind: "node", id: e.source })}>
                            {byId.get(e.source)?.label}
                          </button>
                          <p className="text-[11px] text-muted">{categoryLabel(byId.get(e.source))}</p>
                        </td>
                        <td className="px-4 py-2">
                          <Badge tone={e.type === "CONTRADICTS" ? "danger" : "neutral"}>{EDGE_LABELS[e.type] ?? e.type}</Badge>
                        </td>
                        <td className="px-4 py-2">
                          <button type="button" className="hover:text-evidence" onClick={() => setSelected({ kind: "node", id: e.target })}>
                            {byId.get(e.target)?.label}
                          </button>
                          <p className="text-[11px] text-muted">{categoryLabel(byId.get(e.target))}</p>
                        </td>
                        <td className="px-4 py-2">
                          <Button size="sm" variant="ghost" onClick={() => setSelected({ kind: "edge", id: e.id })}
                                  aria-label={`Show evidence: ${byId.get(e.source)?.label} ${EDGE_LABELS[e.type] ?? e.type} ${byId.get(e.target)?.label}`}>
                            {e.evidence_ids.length} item{e.evidence_ids.length === 1 ? "" : "s"}
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            )}
            <p className="mt-2 text-xs text-muted">
              Showing {shown.nodes.length} of {graph.data.total_nodes} nodes and {shown.edges.length} of {graph.data.total_edges} relationships.
              {focus ? <> Focused on {byId.get(focus)?.label}. <button type="button" className="text-evidence hover:underline" onClick={() => setFocus(null)}>Show all</button></> : null}
            </p>
          </div>
          <div className="space-y-4">
            {selectedEdge ? <EdgeDetails edge={selectedEdge} nodes={byId} /> : selectedNode ? (
              <NodeDetails node={selectedNode} focused={focus === selectedNode.id}
                           onFocus={() => setFocus(focus === selectedNode.id ? null : selectedNode.id)} />
            ) : (
              <Card><p className="text-sm text-muted">Select a node or a relationship to see the evidence behind it.</p></Card>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
