import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { EmptyState, ErrorState } from "@/components/QueryState";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardTitle, Select, Skeleton } from "@/components/ui/primitives";
import { InvestigationView } from "@/features/agents/InvestigationView";
import { ACTIVE, STATUS } from "@/features/agents/labels";
import { api, ApiError } from "@/services/api";
import { usePermission } from "@/stores/auth";
import { toast } from "@/stores/toast";

export function AgentsPage() {
  const [params, setParams] = useSearchParams();
  const cases = useQuery({ queryKey: ["cases", "agents-picker"], queryFn: () => api.cases({}) });
  const items = cases.data?.items ?? [];
  const caseId = params.get("case") ?? items[0]?.id ?? "";

  return (
    <div>
      <PageHeader
        title="AI Agents"
        subtitle="Bounded multi-agent investigations of a case. Every step and citation is recorded; conclusions wait for human review."
        actions={items.length > 0 ? (
          <Select label="Investigation case" hideLabel value={caseId} className="w-80"
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
            Upload and process a case's documents, then start an agent investigation here.
          </EmptyState>
        </Card>
      ) : (
        <CaseAgents key={caseId} caseId={caseId} selected={params.get("run")}
                    onSelect={(run) => setParams({ case: caseId, run })} />
      )}
    </div>
  );
}

function CaseAgents({ caseId, selected, onSelect }: { caseId: string; selected: string | null; onSelect: (id: string) => void }) {
  const qc = useQueryClient();
  const canRun = usePermission("investigations:run");
  const [objective, setObjective] = useState("Explain the discrepancies between the declared values and what is missing to resolve them.");
  const runs = useQuery({ queryKey: ["case-investigations", caseId], queryFn: () => api.caseInvestigations(caseId) });
  const start = useMutation({
    mutationFn: () => api.startInvestigation(caseId, objective),
    onSuccess: (inv) => {
      toast.success("Investigation started", "The agents run in the background.");
      void qc.invalidateQueries({ queryKey: ["case-investigations", caseId] });
      onSelect(inv.id);
    },
    onError: (err) => toast.error("Could not start", err instanceof ApiError ? err.detail : undefined),
  });

  if (runs.isPending) return <Skeleton className="h-[60vh]" />;
  if (runs.isError) return <Card><ErrorState error={runs.error} onRetry={() => void runs.refetch()} /></Card>;
  const active = runs.data.some((r) => ACTIVE.has(r.status));
  const current = runs.data.find((r) => r.id === selected) ?? runs.data[0];

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Card>
          <CardTitle>Start an investigation</CardTitle>
          {!canRun ? (
            <p className="text-sm text-muted">Your role can follow investigations but not start them.</p>
          ) : active ? (
            <p className="text-sm text-muted">This case already has an investigation in progress.</p>
          ) : (
            <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); start.mutate(); }}>
              <label className="block text-xs text-muted">
                Objective
                <textarea value={objective} onChange={(e) => setObjective(e.target.value)} rows={3} maxLength={1000}
                          className="mt-1 w-full rounded-lg border border-line bg-bg/60 px-2 py-1 text-sm text-ink" />
              </label>
              <Button type="submit" loading={start.isPending} disabled={objective.trim().length < 3}>Start investigation</Button>
            </form>
          )}
        </Card>
        <Card>
          <CardTitle>Runs</CardTitle>
          {runs.data.length === 0 ? <p className="text-sm text-muted">No investigation has run on this case yet.</p> : (
            <ul className="space-y-1" aria-label="Investigation runs">
              {runs.data.map((r) => {
                const s = STATUS[r.status] ?? { label: r.status, tone: "neutral" as const };
                return (
                  <li key={r.id}>
                    <button type="button" onClick={() => onSelect(r.id)} aria-current={current?.id === r.id ? "true" : undefined}
                            className="flex w-full items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-elevated/60">
                      <span className="truncate">{new Date(r.created_at).toLocaleString()}</span>
                      <Badge tone={s.tone}>{s.label}</Badge>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </div>
      {current ? <InvestigationView key={current.id} id={current.id} caseId={caseId} /> : null}
    </div>
  );
}
