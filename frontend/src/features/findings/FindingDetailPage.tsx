import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { ExternalLink } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { EmptyState, ErrorState } from "@/components/QueryState";
import { Button } from "@/components/ui/Button";
import { Badge, Card, CardTitle, Mono, Select, Skeleton } from "@/components/ui/primitives";
import { docTypeLabel } from "@/features/documents/labels";
import { SeverityBadge, StatusBadgeFinding } from "@/features/findings/badges";
import {
  findingTypeLabel, formatMoney, formatScore, NOTE_REQUIRED, STATUS_LABELS, STATUSES,
} from "@/features/findings/labels";
import { PriorityBadge } from "@/features/investigations/InvestigationsPage";
import { api, ApiError } from "@/services/api";
import { usePermission } from "@/stores/auth";
import { toast } from "@/stores/toast";
import type { EvidenceOut, FindingDetail, FindingStatus } from "@/types/api";

export function FindingDetailPage() {
  const { findingId = "" } = useParams();
  const finding = useQuery({ queryKey: ["finding", findingId], queryFn: () => api.finding(findingId) });

  if (finding.isPending) return <Skeleton className="h-[60vh]" />;
  if (finding.isError) return <Card><ErrorState error={finding.error} onRetry={() => void finding.refetch()} /></Card>;
  const f = finding.data;
  return (
    <div>
      <PageHeader
        title={f.title}
        subtitle={<span className="flex flex-wrap items-center gap-2">
          {findingTypeLabel(f.type)} · <SeverityBadge severity={f.severity} /> <StatusBadgeFinding status={f.status} />
          {f.active ? null : <Badge tone="warning">No longer detected by the latest comparison</Badge>}
          · <Link to={`/investigations/${f.case_id}`} className="text-evidence hover:underline">{f.case_title}</Link>
        </span>}
      />
      <div className="mb-6 grid gap-3 sm:grid-cols-3">
        <Score label="Anomaly score" value={formatScore(f.anomaly_score)}
               hint="Size of the inconsistency (0 to 1). It is not a likelihood of wrongdoing." />
        <Score label="Evidence confidence" value={formatScore(f.evidence_confidence)}
               hint="Lowest measured confidence of the cited fields." />
        <Score label="Investigation priority" value={<PriorityBadge priority={f.priority} />}
               hint="What to review first, from severity and evidence confidence." />
      </div>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 space-y-6">
          <Card>
            <CardTitle>Observation</CardTitle>
            {f.difference ? (
              <p className="mb-3 text-sm">Difference: <Mono className="text-base text-ink">{formatMoney(f.difference, f.currency)}</Mono></p>
            ) : null}
            <p className="whitespace-pre-line text-sm leading-relaxed">{f.explanation}</p>
            <h3 className="mt-5 text-xs font-semibold uppercase tracking-[0.14em] text-muted">Limitations</h3>
            {f.limitations.length ? (
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted">
                {f.limitations.map((l) => <li key={l}>{l}</li>)}
              </ul>
            ) : <p className="mt-2 text-sm text-muted">None recorded by the rule.</p>}
            <h3 className="mt-5 text-xs font-semibold uppercase tracking-[0.14em] text-muted">Recommended action</h3>
            <p className="mt-2 text-sm">{f.recommended_action}</p>
            <h3 className="mt-5 text-xs font-semibold uppercase tracking-[0.14em] text-muted">Severity rationale</h3>
            <p className="mt-2 text-sm text-muted">{f.severity_rationale}</p>
            <p className="mt-4 text-[11px] text-muted">
              Detected by <Mono>{f.detected_by}</Mono> (deterministic rule) · last detected {new Date(f.last_detected_at).toLocaleString()}
            </p>
          </Card>
          <EvidenceTable finding={f} />
        </div>
        <div className="space-y-6">
          <ReviewPanel finding={f} />
          <HistoryPanel finding={f} />
        </div>
      </div>
    </div>
  );
}

function Score({ label, value, hint }: { label: string; value: React.ReactNode; hint: string }) {
  return (
    <div className="panel p-4" aria-label={`${label}: ${typeof value === "string" ? value : ""}`.trim()}>
      <p className="text-xs text-muted">{label}</p>
      <div className="tabular mt-2 font-mono text-xl font-semibold">{value}</div>
      <p className="mt-1 text-[11px] text-muted">{hint}</p>
    </div>
  );
}

function EvidenceTable({ finding }: { finding: FindingDetail }) {
  if ((finding.evidence ?? []).length === 0) {
    return (
      <Card>
        <CardTitle>Evidence</CardTitle>
        <EmptyState title="Based on an absence">
          This finding records that an expected document is missing, so there is no field to cite.
          It can't be confirmed until evidence exists.
        </EmptyState>
      </Card>
    );
  }
  return (
    <Card className="overflow-x-auto p-0">
      <div className="p-5 pb-0"><CardTitle>Evidence ({(finding.evidence ?? []).length})</CardTitle></div>
      <table className="w-full min-w-[640px] text-left text-sm" aria-label="Evidence items">
        <thead className="border-b border-line text-xs uppercase tracking-wider text-muted">
          <tr>
            <th scope="col" className="px-5 py-2 font-medium">Document</th>
            <th scope="col" className="px-3 py-2 font-medium">Field</th>
            <th scope="col" className="px-3 py-2 font-medium">Value</th>
            <th scope="col" className="px-3 py-2 font-medium">Where</th>
            <th scope="col" className="px-3 py-2 font-medium">Confidence</th>
            <th scope="col" className="px-5 py-2 font-medium"><span className="sr-only">Open</span></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {(finding.evidence ?? []).map((e) => <EvidenceRow key={e.id} e={e} />)}
        </tbody>
      </table>
    </Card>
  );
}

function EvidenceRow({ e }: { e: EvidenceOut }) {
  const where = e.page_number != null ? `page ${e.page_number}` : e.location ?? "—";
  const href = `/documents/${e.document_id}${e.extracted_field_id ? `?field=${e.extracted_field_id}` : ""}`;
  return (
    <tr>
      <td className="px-5 py-2.5">
        <p className="font-medium">{docTypeLabel(e.doc_type)}</p>
        <p className="text-xs text-muted">{e.document_filename}</p>
      </td>
      <td className="px-3 py-2.5 text-xs">
        {e.field_name.replace(/_/g, " ")}
        <Badge tone={e.role === "conflicting" ? "danger" : e.role === "supporting" ? "evidence" : "neutral"}>{e.role}</Badge>
      </td>
      <td className="px-3 py-2.5"><Mono className="text-sm text-ink">{e.value ?? "null"}</Mono></td>
      <td className="px-3 py-2.5 text-xs text-muted">{where}</td>
      <td className="px-3 py-2.5"><Mono>{formatScore(e.confidence)}</Mono></td>
      <td className="px-5 py-2.5">
        {e.extracted_field_id ? (
          <Link to={href} className="inline-flex items-center gap-1 whitespace-nowrap text-xs text-evidence hover:underline"
                aria-label={`Open ${e.document_filename} at ${where}`}>
            Open at source <ExternalLink className="h-3 w-3" aria-hidden />
          </Link>
        ) : <span className="text-xs text-warning">field replaced; re-run the comparison</span>}
      </td>
    </tr>
  );
}

function ReviewPanel({ finding }: { finding: FindingDetail }) {
  const qc = useQueryClient();
  const canReview = usePermission("findings:review");
  const canComment = usePermission("findings:comment");
  const [target, setTarget] = useState<FindingStatus | "">("");
  const [note, setNote] = useState("");
  const [comment, setComment] = useState("");
  const needsNote = target !== "" && NOTE_REQUIRED.includes(target);
  const blockedConfirm = target === "confirmed_observation" && (finding.evidence ?? []).length === 0;

  const refresh = (data?: FindingDetail) => {
    if (data) qc.setQueryData(["finding", finding.id], data);
    void qc.invalidateQueries({ queryKey: ["finding", finding.id] });
    void qc.invalidateQueries({ queryKey: ["findings"] });
    void qc.invalidateQueries({ queryKey: ["case-findings", finding.case_id] });
  };
  const decide = useMutation({
    mutationFn: () => api.setFindingStatus(finding.id, { status: target as FindingStatus, note: note.trim() || null }),
    onSuccess: (data) => {
      refresh(data);
      toast.success(`Marked as ${STATUS_LABELS[data.status].toLowerCase()}`);
      setTarget("");
      setNote("");
    },
    onError: (err) => toast.error("Decision not recorded", err instanceof ApiError ? err.detail : undefined),
  });
  const addComment = useMutation({
    mutationFn: () => api.addFindingComment(finding.id, comment.trim()),
    onSuccess: () => { refresh(); setComment(""); toast.success("Comment added"); },
    onError: (err) => toast.error("Comment not saved", err instanceof ApiError ? err.detail : undefined),
  });

  return (
    <Card>
      <CardTitle>Review</CardTitle>
      {canReview ? (
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); decide.mutate(); }}>
          <Select label="New status" value={target} onChange={(e) => setTarget(e.target.value as FindingStatus | "")}>
            <option value="">Choose a status</option>
            {STATUSES.filter((s) => s !== finding.status).map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
          </Select>
          <div className="space-y-1.5">
            <label htmlFor="decision-note" className="block text-xs font-medium text-muted">
              Note{needsNote ? " (required)" : " (optional)"}
            </label>
            <textarea id="decision-note" value={note} onChange={(e) => setNote(e.target.value)} rows={3} maxLength={4000}
                      className="w-full rounded-lg border border-line bg-bg/60 px-3 py-2 text-sm" />
          </div>
          {blockedConfirm ? (
            <p role="note" className="rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
              A finding without evidence items can't be confirmed. Request the missing document or mark the finding as
              needing more evidence.
            </p>
          ) : null}
          <Button type="submit" loading={decide.isPending}
                  disabled={!target || (needsNote && !note.trim()) || blockedConfirm}>
            Record decision
          </Button>
        </form>
      ) : (
        <p className="text-xs text-muted">Your role can read findings but not record decisions.</p>
      )}
      {canComment ? (
        <form className="mt-6 space-y-2 border-t border-line pt-4" onSubmit={(e) => { e.preventDefault(); addComment.mutate(); }}>
          <label htmlFor="finding-comment" className="block text-xs font-medium text-muted">Comment</label>
          <textarea id="finding-comment" value={comment} onChange={(e) => setComment(e.target.value)} rows={2} maxLength={4000}
                    className="w-full rounded-lg border border-line bg-bg/60 px-3 py-2 text-sm" />
          <Button type="submit" size="sm" variant="secondary" loading={addComment.isPending} disabled={!comment.trim()}>
            Add comment
          </Button>
        </form>
      ) : null}
    </Card>
  );
}

function HistoryPanel({ finding }: { finding: FindingDetail }) {
  const items = [
    ...(finding.decisions ?? []).map((d) => ({
      id: d.id, at: d.created_at, who: d.actor_email ?? "former member",
      text: `${STATUS_LABELS[d.from_status as FindingStatus] ?? d.from_status} → ${STATUS_LABELS[d.to_status as FindingStatus] ?? d.to_status}`,
      note: d.note, kind: "decision" as const,
    })),
    ...(finding.comments ?? []).map((c) => ({
      id: c.id, at: c.created_at, who: c.user_email ?? "former member", text: "Comment", note: c.body, kind: "comment" as const,
    })),
  ].sort((a, b) => a.at.localeCompare(b.at));
  return (
    <Card>
      <CardTitle>History</CardTitle>
      {items.length === 0 ? <p className="text-xs text-muted">No decisions or comments yet.</p> : (
        <ol className="space-y-3" aria-label="Decision history">
          {items.map((i) => (
            <li key={i.id} className={clsx("border-l-2 pl-3", i.kind === "decision" ? "border-evidence/60" : "border-line")}>
              <p className="text-sm font-medium">{i.text}</p>
              {i.note ? <p className="mt-0.5 whitespace-pre-line text-sm text-muted">{i.note}</p> : null}
              <p className="mt-0.5 text-[11px] text-muted">{i.who} · <Mono>{new Date(i.at).toLocaleString()}</Mono></p>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
