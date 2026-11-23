import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { CheckCircle2, CircleDashed, CircleX, Loader2, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import { ErrorState } from "@/components/QueryState";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardTitle, Mono, Skeleton } from "@/components/ui/primitives";
import { AgentOutput } from "@/features/agents/AgentOutputs";
import { ACTIVE, AGENTS, agentTitle, BUDGET_LABELS, EVENT_LABELS, STATUS } from "@/features/agents/labels";
import { api, ApiError } from "@/services/api";
import { streamEvents } from "@/services/sse";
import { usePermission } from "@/stores/auth";
import { toast } from "@/stores/toast";
import type { AgentRunOut, InvestigationDetail } from "@/types/api";

export interface AgentEvent {
  seq: number;
  agent: string | null;
  type: string;
  data: Record<string, unknown>;
  created_at: string;
  status: string;
}

/** Persisted agent events over SSE; refreshes the investigation when its status changes. */
function useAgentEvents(id: string, live: boolean, onStatus: () => void) {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  useEffect(() => {
    const controller = new AbortController();
    let lastStatus = "";
    setEvents([]);
    streamEvents(`/investigations/${id}/events`, {
      signal: controller.signal,
      onMessage: (msg) => {
        if (msg.event === "end") return;
        const ev = msg.data as AgentEvent;
        setEvents((list) => (list.some((e) => e.seq === ev.seq) ? list : [...list, ev]));
        if (ev.status !== lastStatus || ev.type.startsWith("agent_")) {
          lastStatus = ev.status;
          onStatus();
        }
      },
    }).catch(() => undefined);
    return () => controller.abort();
    // Restart the stream when the run becomes live again (for example after approval).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, live]);
  return events;
}

function eventDetail(e: AgentEvent): string {
  const d = e.data;
  switch (e.type) {
    case "tool_called":
    case "tool_failed":
      return String(d.tool ?? "");
    case "tool_rejected":
      return `${String(d.tool)}: ${String(d.reason).replace(/_/g, " ")}`;
    case "reference_rejected":
      return String(d.reason).replace(/_/g, " ");
    case "agent_completed":
      return String(d.summary ?? "");
    case "agent_failed":
    case "investigation_failed":
      return String(d.error ?? d.reason ?? "");
    case "budget_exhausted":
      return `${String(d.limit).replace(/_/g, " ")} reached (${String(d.used)} of ${String(d.maximum)})`;
    default:
      return "";
  }
}

const WARN = new Set(["tool_rejected", "reference_rejected", "output_invalid", "agent_failed", "budget_exhausted", "investigation_failed"]);

function StepIcon({ run }: { run: AgentRunOut | undefined }) {
  if (!run) return <CircleDashed className="h-4 w-4 text-muted" aria-label="Not started" />;
  if (run.status === "running") return <Loader2 className="h-4 w-4 animate-spin text-evidence" aria-label="Running" />;
  if (run.status === "succeeded") return <CheckCircle2 className="h-4 w-4 text-primary" aria-label="Succeeded" />;
  return <CircleX className="h-4 w-4 text-danger" aria-label="Failed" />;
}

function EvidenceRequestForm({ id }: { id: string }) {
  const qc = useQueryClient();
  const [types, setTypes] = useState("");
  const [note, setNote] = useState("");
  const mutation = useMutation({
    mutationFn: () => api.requestEvidence(id, types.split(",").map((t) => t.trim()).filter(Boolean), note),
    onSuccess: () => {
      toast.success("Evidence request recorded");
      setTypes("");
      setNote("");
      void qc.invalidateQueries({ queryKey: ["investigation", id] });
    },
    onError: (err) => toast.error("Request failed", err instanceof ApiError ? err.detail : undefined),
  });
  return (
    <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); mutation.mutate(); }}>
      <label className="block text-xs text-muted">
        Document types (comma-separated)
        <input value={types} onChange={(e) => setTypes(e.target.value)} placeholder="freight_invoice, insurance_policy"
               className="mt-1 h-9 w-full rounded-lg border border-line bg-bg/60 px-2 text-sm text-ink" />
      </label>
      <label className="block text-xs text-muted">
        Note
        <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2}
                  className="mt-1 w-full rounded-lg border border-line bg-bg/60 px-2 py-1 text-sm text-ink" />
      </label>
      <Button type="submit" size="sm" variant="secondary" loading={mutation.isPending}
              disabled={!types.trim() || note.trim().length < 3}>Request evidence</Button>
    </form>
  );
}

export function InvestigationView({ id, caseId }: { id: string; caseId: string }) {
  const qc = useQueryClient();
  const canApprove = usePermission("findings:review");
  const canRequest = usePermission("findings:comment");
  const [open, setOpen] = useState<string | null>(null);
  const detail = useQuery({ queryKey: ["investigation", id], queryFn: () => api.investigation(id) });
  const live = detail.data ? ACTIVE.has(detail.data.status) && detail.data.status !== "awaiting_review" : true;
  const events = useAgentEvents(id, live, () => {
    void qc.invalidateQueries({ queryKey: ["investigation", id] });
    void qc.invalidateQueries({ queryKey: ["case-investigations", caseId] });
  });
  const approve = useMutation({
    mutationFn: () => api.approveInvestigation(id),
    onSuccess: () => {
      toast.success("Approved", "The report step is running.");
      void qc.invalidateQueries({ queryKey: ["investigation", id] });
      void qc.invalidateQueries({ queryKey: ["case-investigations", caseId] });
    },
    onError: (err) => toast.error("Approval failed", err instanceof ApiError ? err.detail : undefined),
  });

  if (detail.isPending) return <Skeleton className="h-[60vh]" />;
  if (detail.isError) return <Card><ErrorState error={detail.error} onRetry={() => void detail.refetch()} /></Card>;
  const d: InvestigationDetail = detail.data;
  const status = STATUS[d.status] ?? { label: d.status, tone: "neutral" as const };
  const outputs = ((d.result as { agents?: Record<string, Record<string, unknown>> }).agents ?? {});
  const runs = new Map<string, AgentRunOut>();
  for (const r of d.agent_runs ?? []) runs.set(r.agent, r);
  const usage = d.usage as Record<string, number>;
  const budget = d.budget as Record<string, number>;

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="min-w-0 space-y-4">
        <Card>
          <CardTitle action={<Badge tone={status.tone}>{status.label}</Badge>}>Investigation</CardTitle>
          <p className="text-sm">{d.objective}</p>
          {d.error ? <p className="mt-2 text-sm text-danger" role="alert">{d.error}</p> : null}
          {d.status === "awaiting_review" ? (
            <div className="mt-4 flex flex-wrap items-center gap-3 rounded-lg border border-warning/40 bg-warning/5 p-3">
              <ShieldCheck className="h-5 w-5 text-warning" aria-hidden />
              <p className="flex-1 text-sm">
                The agents have finished. Review their outputs below; the report is drafted only after approval.
              </p>
              {canApprove ? (
                <Button size="sm" loading={approve.isPending} onClick={() => approve.mutate()}>Approve and write report</Button>
              ) : (
                <span className="text-xs text-muted">A reviewer must approve.</span>
              )}
            </div>
          ) : null}
          <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {BUDGET_LABELS.map(([used, max, label]) => (
              <div key={used}>
                <dt className="text-xs text-muted">{label}</dt>
                <dd className="tabular text-sm" aria-label={`${label}: ${usage[used] ?? 0} of ${budget[max]}`}>
                  {Math.round(usage[used] ?? 0)} / {budget[max]}
                </dd>
              </div>
            ))}
          </dl>
          {usage.unmetered_calls ? (
            <p className="mt-2 text-xs text-muted">{usage.unmetered_calls} model call(s) reported no token counts and are not included.</p>
          ) : null}
        </Card>

        <Card className="p-0">
          <ol aria-label="Agent steps" className="divide-y divide-line">
            {AGENTS.map((a) => {
              const run = runs.get(a.key);
              const out = outputs[a.key];
              const expanded = open === a.key;
              return (
                <li key={a.key}>
                  <button type="button" disabled={!out} aria-expanded={expanded} onClick={() => setOpen(expanded ? null : a.key)}
                          className={clsx("flex w-full items-center gap-3 px-4 py-3 text-left", out && "hover:bg-elevated/60")}>
                    <StepIcon run={run} />
                    <span className="w-44 shrink-0 text-sm font-medium">{a.title}</span>
                    <span className="min-w-0 flex-1 truncate text-xs text-muted">{run?.output_summary || run?.error || ""}</span>
                    {run?.duration_ms != null ? <Mono className="text-muted">{(run.duration_ms / 1000).toFixed(1)} s</Mono> : null}
                  </button>
                  {expanded && out ? (
                    <div className="border-t border-line bg-bg/40 px-4 py-3">
                      <AgentOutput agent={a.key} out={out} caseId={caseId} />
                      {run ? (
                        <p className="mt-3 text-[11px] text-muted">
                          {run.model ?? "no model"} · {run.prompt_version} · {run.tool_calls} tool call(s)
                          {run.tokens != null ? ` · ${run.tokens} tokens` : ""}
                        </p>
                      ) : null}
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ol>
        </Card>
      </div>

      <div className="space-y-4 xl:max-h-[84vh] xl:overflow-auto">
        <Card>
          <CardTitle>Event log</CardTitle>
          {events.length === 0 ? <p className="text-sm text-muted">No events yet.</p> : (
            <ol className="space-y-1.5 text-xs" aria-label="Agent events">
              {events.map((e) => (
                <li key={e.seq} className="flex gap-2">
                  <Mono className="w-7 shrink-0 text-muted">{e.seq}</Mono>
                  <span className="min-w-0">
                    <span className={clsx(WARN.has(e.type) ? "text-warning" : "text-ink")}>{EVENT_LABELS[e.type] ?? e.type}</span>
                    {e.agent ? <span className="text-muted"> · {agentTitle(e.agent)}</span> : null}
                    {eventDetail(e) ? <span className="block break-words text-muted">{eventDetail(e)}</span> : null}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </Card>
        {canRequest ? (
          <Card>
            <CardTitle>Request more evidence</CardTitle>
            <EvidenceRequestForm id={id} />
            {(d.evidence_requests ?? []).length > 0 ? (
              <ul className="mt-3 space-y-1 text-xs" aria-label="Evidence requests">
                {(d.evidence_requests ?? []).map((r) => (
                  <li key={r.id}><span className="font-medium">{r.document_types.join(", ")}</span>: {r.note}</li>
                ))}
              </ul>
            ) : null}
          </Card>
        ) : null}
      </div>
    </div>
  );
}
