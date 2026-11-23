import { useInfiniteQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { EmptyState, ErrorState } from "@/components/QueryState";
import { Button } from "@/components/ui/Button";
import { Mono, Select, Skeleton } from "@/components/ui/primitives";
import { DOC_TYPE_LABELS, docTypeLabel, formatBytes } from "@/features/documents/labels";
import { StatusBadge } from "@/features/documents/StatusBadge";
import { api } from "@/services/api";

export function DocumentsPage() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [docType, setDocType] = useState("");
  const docs = useInfiniteQuery({
    queryKey: ["documents", { q, status, docType }],
    queryFn: ({ pageParam }) => api.documents({ cursor: pageParam, q, status, doc_type: docType }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? null,
    refetchInterval: (query) =>
      query.state.data?.pages.some((p) => p.items.some((d) => d.status === "uploaded" || d.status === "processing")) ? 5000 : false,
  });
  const rows = docs.data?.pages.flatMap((p) => p.items) ?? [];
  const filtered = Boolean(q || status || docType);

  return (
    <div>
      <PageHeader title="Documents" subtitle="Every document across this organization's investigations." />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <label className="relative">
          <span className="sr-only">Search by filename</span>
          <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted" aria-hidden />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search filename"
                 className="h-10 w-64 rounded-lg border border-line bg-bg/60 pl-9 pr-3 text-sm" />
        </label>
        <Select label="Status" value={status} onChange={(e) => setStatus(e.target.value)} className="w-40">
          <option value="">Any status</option>
          {["uploaded", "processing", "completed", "failed"].map((s) => <option key={s} value={s}>{s}</option>)}
        </Select>
        <Select label="Document type" value={docType} onChange={(e) => setDocType(e.target.value)} className="w-56">
          <option value="">Any type</option>
          {Object.entries(DOC_TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </Select>
      </div>
      <div className="panel overflow-hidden">
        {docs.isPending ? (
          <div className="space-y-2 p-4">{Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-10" />)}</div>
        ) : docs.isError ? (
          <ErrorState error={docs.error} onRetry={() => void docs.refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState title={filtered ? "No documents match these filters" : "No documents yet"}
                      action={!filtered ? <Link to="/investigations" className="text-sm text-evidence hover:underline">Go to investigations</Link> : undefined}>
            {filtered ? "Change the search or filters." : "Documents are uploaded into an investigation case."}
          </EmptyState>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="border-b border-line text-xs uppercase tracking-wider text-muted">
              <tr>
                <th scope="col" className="px-4 py-3 font-medium">Document</th>
                <th scope="col" className="px-4 py-3 font-medium">Type</th>
                <th scope="col" className="px-4 py-3 font-medium">Status</th>
                <th scope="col" className="hidden px-4 py-3 font-medium md:table-cell">Pages</th>
                <th scope="col" className="hidden px-4 py-3 font-medium lg:table-cell">SHA-256</th>
                <th scope="col" className="hidden px-4 py-3 font-medium lg:table-cell">Uploaded</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((d) => (
                <tr key={d.id} className="hover:bg-elevated/50">
                  <td className="px-4 py-3">
                    <Link to={`/documents/${d.id}`} className="font-medium hover:text-evidence">{d.original_filename}</Link>
                    <p className="text-xs text-muted">{d.mime_type} · {formatBytes(d.size_bytes)}</p>
                  </td>
                  <td className="px-4 py-3 text-muted">{docTypeLabel(d.doc_type)}</td>
                  <td className="px-4 py-3"><StatusBadge status={d.status} stage={d.current_stage} /></td>
                  <td className="hidden px-4 py-3 md:table-cell"><Mono>{d.page_count ?? "—"}</Mono></td>
                  <td className="hidden px-4 py-3 lg:table-cell" title={d.sha256}><Mono className="text-muted">{d.sha256.slice(0, 12)}…</Mono></td>
                  <td className="hidden px-4 py-3 lg:table-cell"><Mono className="text-muted">{new Date(d.uploaded_at).toLocaleString()}</Mono></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {docs.hasNextPage ? (
        <div className="mt-4 flex justify-center">
          <Button variant="secondary" loading={docs.isFetchingNextPage} onClick={() => void docs.fetchNextPage()}>Load more</Button>
        </div>
      ) : null}
    </div>
  );
}
