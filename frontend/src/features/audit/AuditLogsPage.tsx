import { useInfiniteQuery } from "@tanstack/react-query";

import { PageHeader } from "@/components/PageHeader";
import { EmptyState, ErrorState } from "@/components/QueryState";
import { Button } from "@/components/ui/Button";
import { Badge, Mono, Skeleton } from "@/components/ui/primitives";
import { api } from "@/services/api";
import { usePermission } from "@/stores/auth";
import type { AuditLog } from "@/types/api";

const actionTone = (action: string) =>
  action.includes("failed") || action.includes("reuse") || action.includes("remove")
    ? "danger"
    : action.startsWith("auth.")
      ? "evidence"
      : "primary";

export function AuditLogsPage() {
  const allowed = usePermission("audit:read");
  const logs = useInfiniteQuery({
    queryKey: ["audit-logs"],
    queryFn: ({ pageParam }) => api.auditLogs(pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? null,
    enabled: allowed,
  });

  if (!allowed) {
    return (
      <div>
        <PageHeader title="Audit Logs" />
        <div className="panel"><EmptyState title="Your role can't view the audit log.">
          Ask an Organization Admin or Investigation Manager.
        </EmptyState></div>
      </div>
    );
  }

  const rows: AuditLog[] = logs.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div>
      <PageHeader title="Audit Logs" subtitle="Append-only record of security-relevant actions in this organization." />
      <div className="panel overflow-hidden">
        {logs.isPending ? (
          <div className="space-y-2 p-4" aria-busy>{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-8" />)}</div>
        ) : logs.isError ? (
          <ErrorState error={logs.error} onRetry={() => void logs.refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState title="No audit events yet" />
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="border-b border-line text-xs uppercase tracking-wider text-muted">
              <tr>
                <th scope="col" className="px-4 py-3 font-medium">Time</th>
                <th scope="col" className="px-4 py-3 font-medium">Action</th>
                <th scope="col" className="px-4 py-3 font-medium">Actor</th>
                <th scope="col" className="hidden px-4 py-3 font-medium md:table-cell">Resource</th>
                <th scope="col" className="hidden px-4 py-3 font-medium lg:table-cell">IP</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((row) => (
                <tr key={row.id} className="hover:bg-elevated/50">
                  <td className="whitespace-nowrap px-4 py-2.5"><Mono className="text-muted">{new Date(row.created_at).toLocaleString()}</Mono></td>
                  <td className="px-4 py-2.5"><Badge tone={actionTone(row.action)}>{row.action}</Badge></td>
                  <td className="px-4 py-2.5 text-muted">{row.actor_email ?? "—"}</td>
                  <td className="hidden px-4 py-2.5 md:table-cell">
                    {row.resource_type ? <Mono className="text-muted">{row.resource_type}:{row.resource_id?.slice(0, 8)}</Mono> : "—"}
                  </td>
                  <td className="hidden px-4 py-2.5 lg:table-cell"><Mono className="text-muted">{row.ip ?? "—"}</Mono></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {logs.hasNextPage ? (
        <div className="mt-4 flex justify-center">
          <Button variant="secondary" loading={logs.isFetchingNextPage} onClick={() => void logs.fetchNextPage()}>
            Load older events
          </Button>
        </div>
      ) : null}
    </div>
  );
}
