import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { EmptyState, ErrorState } from "@/components/QueryState";
import { Button } from "@/components/ui/Button";
import { Mono, Select, Skeleton } from "@/components/ui/primitives";
import { SeverityBadge, StatusBadgeFinding } from "@/features/findings/badges";
import { FINDING_TYPES, formatMoney, formatScore, STATUS_LABELS, STATUSES } from "@/features/findings/labels";
import { PriorityBadge } from "@/features/investigations/InvestigationsPage";
import { api } from "@/services/api";

export function FindingsPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState("");
  const [severity, setSeverity] = useState("");
  const [priority, setPriority] = useState("");
  const [type, setType] = useState("");
  const [includeInactive, setIncludeInactive] = useState(false);
  const [params, setParams] = useSearchParams();
  const caseId = params.get("case") ?? "";
  const findings = useInfiniteQuery({
    queryKey: ["findings", { status, severity, priority, type, includeInactive, caseId }],
    queryFn: ({ pageParam }) =>
      api.findings({ cursor: pageParam, status, severity, priority, type, include_inactive: includeInactive,
                     case_id: caseId || undefined }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? null,
  });
  const rows = findings.data?.pages.flatMap((p) => p.items) ?? [];
  const filtered = Boolean(status || severity || priority || type || includeInactive || caseId);

  return (
    <div>
      <PageHeader
        title="Findings"
        subtitle="Observations from comparing the documents of each case. Each one cites its source fields and needs a human decision."
      />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Select label="Status" value={status} onChange={(e) => setStatus(e.target.value)} className="w-48">
          <option value="">Any status</option>
          {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
        </Select>
        <Select label="Severity" value={severity} onChange={(e) => setSeverity(e.target.value)} className="w-36">
          <option value="">Any severity</option>
          {["high", "medium", "low", "info"].map((s) => <option key={s} value={s}>{s}</option>)}
        </Select>
        <Select label="Priority" value={priority} onChange={(e) => setPriority(e.target.value)} className="w-36">
          <option value="">Any priority</option>
          {["high", "medium", "low"].map((p) => <option key={p} value={p}>{p}</option>)}
        </Select>
        <Select label="Type" value={type} onChange={(e) => setType(e.target.value)} className="w-52">
          <option value="">Any type</option>
          {Object.entries(FINDING_TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </Select>
        <label className="flex h-10 items-center gap-2 text-xs text-muted">
          <input type="checkbox" checked={includeInactive} onChange={(e) => setIncludeInactive(e.target.checked)} />
          Include findings no longer detected
        </label>
        {caseId ? (
          <span className="flex h-10 items-center gap-2 text-xs text-muted">
            Showing one case{rows[0]?.case_title ? `: ${rows[0].case_title}` : ""}
            <Button size="sm" variant="ghost" onClick={() => setParams({})}>Show all cases</Button>
          </span>
        ) : null}
      </div>
      <div className="panel overflow-x-auto">
        {findings.isPending ? (
          <div className="space-y-2 p-4">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-12" />)}</div>
        ) : findings.isError ? (
          <ErrorState error={findings.error} onRetry={() => void findings.refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState
            title={filtered ? "No findings match these filters" : "No findings yet"}
            action={filtered ? undefined : (
              <Button size="sm" variant="secondary" onClick={() => navigate("/investigations")}>Open investigations</Button>
            )}
          >
            {filtered
              ? "Change the filters."
              : "Findings appear after the documents of a case are processed and compared."}
          </EmptyState>
        ) : (
          <table className="w-full min-w-[960px] text-left text-sm">
            <thead className="border-b border-line text-xs uppercase tracking-wider text-muted">
              <tr>
                <th scope="col" className="px-4 py-3 font-medium">Finding</th>
                <th scope="col" className="px-4 py-3 font-medium">Severity</th>
                <th scope="col" className="px-4 py-3 font-medium">Priority</th>
                <th scope="col" className="px-4 py-3 font-medium" title="Magnitude of the inconsistency, 0 to 1">Anomaly</th>
                <th scope="col" className="px-4 py-3 font-medium" title="Lowest measured confidence of the cited fields">Evidence conf.</th>
                <th scope="col" className="px-4 py-3 font-medium">Evidence</th>
                <th scope="col" className="px-4 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((f) => (
                <tr key={f.id} className="hover:bg-elevated/50">
                  <td className="px-4 py-3">
                    <Link to={`/findings/${f.id}`} className="font-medium hover:text-evidence">{f.title}</Link>
                    <p className="text-xs text-muted">
                      {FINDING_TYPES[f.type] ?? f.type} · <Link to={`/investigations/${f.case_id}`} className="hover:text-evidence">{f.case_title}</Link>
                      {f.difference ? <> · <Mono>{formatMoney(f.difference, f.currency)}</Mono></> : null}
                      {f.active ? null : <> · <span className="text-warning">no longer detected</span></>}
                    </p>
                  </td>
                  <td className="px-4 py-3"><SeverityBadge severity={f.severity} /></td>
                  <td className="px-4 py-3"><PriorityBadge priority={f.priority} /></td>
                  <td className="px-4 py-3"><Mono>{formatScore(f.anomaly_score)}</Mono></td>
                  <td className="px-4 py-3"><Mono>{formatScore(f.evidence_confidence)}</Mono></td>
                  <td className="px-4 py-3">
                    {f.evidence_status === "absence"
                      ? <span className="text-xs text-muted">absence</span>
                      : <Mono>{f.evidence_count} items</Mono>}
                  </td>
                  <td className="px-4 py-3"><StatusBadgeFinding status={f.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {findings.hasNextPage ? (
        <div className="mt-4 flex justify-center">
          <Button variant="secondary" loading={findings.isFetchingNextPage} onClick={() => void findings.fetchNextPage()}>Load more</Button>
        </div>
      ) : null}
    </div>
  );
}
