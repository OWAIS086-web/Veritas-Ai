import { useInfiniteQuery } from "@tanstack/react-query";
import { FolderPlus, Search } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { EmptyState, ErrorState } from "@/components/QueryState";
import { Button } from "@/components/ui/Button";
import { Badge, Mono, Select, Skeleton } from "@/components/ui/primitives";
import { INVESTIGATION_TYPES } from "@/features/documents/labels";
import { api } from "@/services/api";
import { usePermission } from "@/stores/auth";

const PRIORITY_TONE = { low: "neutral", medium: "evidence", high: "warning", critical: "danger" } as const;

export function PriorityBadge({ priority }: { priority: string }) {
  return <Badge tone={PRIORITY_TONE[priority as keyof typeof PRIORITY_TONE] ?? "neutral"}>{priority}</Badge>;
}

export function InvestigationsPage() {
  const navigate = useNavigate();
  const canCreate = usePermission("cases:write");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const cases = useInfiniteQuery({
    queryKey: ["cases", { q, status, priority }],
    queryFn: ({ pageParam }) => api.cases({ cursor: pageParam, q, status, priority }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? null,
  });
  const rows = cases.data?.pages.flatMap((p) => p.items) ?? [];
  const filtered = Boolean(q || status || priority);

  return (
    <div>
      <PageHeader
        title="Investigations"
        subtitle="Cases group the documents that are examined together."
        actions={canCreate ? (
          <Button icon={<FolderPlus className="h-4 w-4" />} onClick={() => navigate("/investigations/new")}>
            New investigation
          </Button>
        ) : null}
      />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <label className="relative">
          <span className="sr-only">Search investigations</span>
          <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted" aria-hidden />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search title or objective"
                 className="h-10 w-72 rounded-lg border border-line bg-bg/60 pl-9 pr-3 text-sm" />
        </label>
        <Select label="Status" value={status} onChange={(e) => setStatus(e.target.value)} className="w-36">
          <option value="">Any status</option><option value="open">Open</option><option value="closed">Closed</option>
        </Select>
        <Select label="Priority" value={priority} onChange={(e) => setPriority(e.target.value)} className="w-36">
          <option value="">Any priority</option>
          {["low", "medium", "high", "critical"].map((p) => <option key={p} value={p}>{p}</option>)}
        </Select>
      </div>
      <div className="panel overflow-hidden">
        {cases.isPending ? (
          <div className="space-y-2 p-4">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-12" />)}</div>
        ) : cases.isError ? (
          <ErrorState error={cases.error} onRetry={() => void cases.refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState title={filtered ? "No investigations match these filters" : "No investigations yet"}
                      action={canCreate && !filtered ? (
                        <Button size="sm" onClick={() => navigate("/investigations/new")}>Create the first investigation</Button>
                      ) : undefined}>
            {filtered ? "Change the search or filters." : "Create a case and upload its documents to start."}
          </EmptyState>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="border-b border-line text-xs uppercase tracking-wider text-muted">
              <tr>
                <th scope="col" className="px-4 py-3 font-medium">Case</th>
                <th scope="col" className="px-4 py-3 font-medium">Type</th>
                <th scope="col" className="px-4 py-3 font-medium">Priority</th>
                <th scope="col" className="px-4 py-3 font-medium">Documents</th>
                <th scope="col" className="hidden px-4 py-3 font-medium md:table-cell">Findings</th>
                <th scope="col" className="hidden px-4 py-3 font-medium lg:table-cell">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((c) => (
                <tr key={c.id} className="hover:bg-elevated/50">
                  <td className="px-4 py-3">
                    <Link to={`/investigations/${c.id}`} className="font-medium hover:text-evidence">{c.title}</Link>
                    <p className="text-xs text-muted">{c.status === "open" ? "Open" : "Closed"} · {c.created_by_email ?? "unknown"}</p>
                  </td>
                  <td className="px-4 py-3 text-muted">{INVESTIGATION_TYPES[c.investigation_type] ?? c.investigation_type}</td>
                  <td className="px-4 py-3"><PriorityBadge priority={c.priority} /></td>
                  <td className="px-4 py-3">
                    <Mono>{c.documents_completed}/{c.document_count}</Mono>
                    <span className="ml-1 text-xs text-muted">processed</span>
                    {c.documents_failed ? <Badge tone="danger">{c.documents_failed} failed</Badge> : null}
                  </td>
                  <td className="hidden px-4 py-3 md:table-cell">
                    {c.finding_count == null
                      ? <span className="text-xs text-muted">Not compared yet</span>
                      : <Link to={`/findings?case=${c.id}`} className="hover:text-evidence"><Mono>{c.finding_count}</Mono></Link>}
                  </td>
                  <td className="hidden px-4 py-3 lg:table-cell"><Mono className="text-muted">{new Date(c.created_at).toLocaleDateString()}</Mono></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {cases.hasNextPage ? (
        <div className="mt-4 flex justify-center">
          <Button variant="secondary" loading={cases.isFetchingNextPage} onClick={() => void cases.fetchNextPage()}>Load more</Button>
        </div>
      ) : null}
    </div>
  );
}
