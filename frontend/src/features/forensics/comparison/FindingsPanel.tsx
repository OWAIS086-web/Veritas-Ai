import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { useState } from "react";

import { ErrorState } from "@/components/QueryState";
import { Button } from "@/components/ui/Button";
import { Badge, Mono, Select, Skeleton } from "@/components/ui/primitives";
import { SeverityBadge } from "@/features/findings/badges";
import { findingTypeLabel, REVIEW, SOURCE_LABEL } from "@/features/forensics/comparison/labels";
import { ApiError, api } from "@/services/api";
import { usePermission } from "@/stores/auth";
import { toast } from "@/stores/toast";
import type { ComparisonFindingOut, ComparisonReviewStatus } from "@/types/api";

const NOTE_REQUIRED: ComparisonReviewStatus[] = ["confirmed_difference", "dismissed"];

function vlmLine(f: ComparisonFindingOut): string | null {
  const v = f.vlm_assessment as Record<string, unknown> | null;
  if (!v) return null;
  if (v["status"] === "assessed") {
    const seen = v["visible_difference"] === true ? "sees a difference" : "sees no difference";
    const description = typeof v["description"] === "string" ? ` - ${v["description"]}` : "";
    return `Vision model ${seen}${description}`;
  }
  if (v["status"] === "proposed") return `Proposed by the vision model and confirmed by changed pixels: ${String(v["description"] ?? "")}`;
  if (v["status"] === "error") return "The vision-model check failed for this region.";
  return null;
}

function ReviewForm({ comparisonId, finding }: { comparisonId: string; finding: ComparisonFindingOut }) {
  const qc = useQueryClient();
  const [status, setStatus] = useState<ComparisonReviewStatus>(
    finding.review_status === "unreviewed" ? "confirmed_difference" : finding.review_status,
  );
  const [note, setNote] = useState("");
  const needsNote = NOTE_REQUIRED.includes(status) && !note.trim();
  const save = useMutation({
    mutationFn: () => api.reviewComparisonFinding(comparisonId, finding.id, status, note),
    onSuccess: () => {
      toast.success("Review saved", `#${finding.number}: ${REVIEW[status].label}`);
      setNote("");
      void qc.invalidateQueries({ queryKey: ["comparison", comparisonId] });
      void qc.invalidateQueries({ queryKey: ["comparison-reviews", finding.id] });
    },
    onError: (err) => toast.error("Review not saved", err instanceof ApiError ? err.detail : undefined),
  });

  return (
    <form className="space-y-2 border-t border-line pt-3"
          onSubmit={(e) => { e.preventDefault(); if (!needsNote) save.mutate(); }}>
      <Select label="Review decision" value={status}
              onChange={(e) => setStatus(e.target.value as ComparisonReviewStatus)}>
        <option value="confirmed_difference">Confirm the difference</option>
        <option value="needs_more_evidence">Needs more evidence</option>
        <option value="dismissed">Dismiss</option>
        <option value="unreviewed">Back to not reviewed</option>
      </Select>
      <label className="block text-xs text-muted" htmlFor={`note-${finding.id}`}>
        Note{NOTE_REQUIRED.includes(status) ? " (required)" : " (optional)"}
      </label>
      <textarea id={`note-${finding.id}`} value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000}
                rows={3} className="w-full rounded-md border border-line bg-bg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-evidence" />
      <Button type="submit" size="sm" loading={save.isPending} disabled={needsNote}>Save review</Button>
    </form>
  );
}

function History({ comparisonId, findingId }: { comparisonId: string; findingId: string }) {
  const history = useQuery({
    queryKey: ["comparison-reviews", findingId],
    queryFn: () => api.comparisonFindingReviews(comparisonId, findingId),
  });
  if (history.isPending) return <Skeleton className="h-10" />;
  if (history.isError) return <ErrorState error={history.error} onRetry={() => void history.refetch()} />;
  if (history.data.length === 0) return <p className="text-xs text-muted">No review decisions yet.</p>;
  return (
    <ol aria-label="Review history" className="space-y-1 text-xs">
      {history.data.map((h) => (
        <li key={h.id}>
          <span className="text-muted">{new Date(h.created_at).toLocaleString()}</span>{" "}
          {h.actor_email ?? "A former member"}: {REVIEW[h.from_status as ComparisonReviewStatus]?.label ?? h.from_status}
          {" -> "}{REVIEW[h.to_status as ComparisonReviewStatus]?.label ?? h.to_status}
          {h.note ? <span className="block text-muted">"{h.note}"</span> : null}
        </li>
      ))}
    </ol>
  );
}

export function FindingsPanel({ comparisonId, findings, selected, onSelect }: {
  comparisonId: string;
  findings: ComparisonFindingOut[];
  selected: string | null;
  onSelect: (f: ComparisonFindingOut) => void;
}) {
  const canReview = usePermission("findings:review");
  const current = findings.find((f) => f.id === selected) ?? null;

  if (findings.length === 0) {
    return (
      <p className="text-sm text-muted">
        No differences were found on the compared pages: the text matched and no pixel region changed
        beyond the noise thresholds.
      </p>
    );
  }
  return (
    <div className="space-y-3">
      <ul aria-label="Differences" className="space-y-1.5">
        {findings.map((f) => (
          <li key={f.id}>
            <button type="button" onClick={() => onSelect(f)} aria-current={f.id === selected ? "true" : undefined}
                    className={clsx("w-full rounded-md border px-3 py-2 text-left text-sm focus:outline-none focus:ring-2 focus:ring-evidence",
                                    f.id === selected ? "border-evidence bg-elevated" : "border-line hover:bg-elevated")}>
              <span className="flex items-center gap-2">
                <Mono>#{f.number}</Mono>
                <span className="font-medium">{findingTypeLabel(f.type)}</span>
                <span className="ml-auto"><SeverityBadge severity={f.severity} /></span>
              </span>
              <span className="mt-1 block text-xs text-muted">
                {f.test_page ? `Test page ${f.test_page}` : `Original page ${f.original_page}`}
                {" · "}evidence confidence <span className="tabular">{Number(f.evidence_confidence).toFixed(2)}</span>
                {" · "}{REVIEW[f.review_status].label}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {current ? (
        <article aria-label={`Difference ${current.number}`} className="space-y-2 rounded-md border border-line p-3 text-sm">
          <p>{current.explanation}</p>
          {current.original_text || current.test_text ? (
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
              <dt className="text-muted">Original</dt><dd><Mono>{current.original_text ?? "-"}</Mono></dd>
              <dt className="text-muted">Test</dt><dd><Mono>{current.test_text ?? "-"}</Mono></dd>
            </dl>
          ) : null}
          <div className="flex flex-wrap gap-1">
            {current.sources.map((s) => <Badge key={s} tone="evidence">{SOURCE_LABEL[s] ?? s}</Badge>)}
            <Badge tone={REVIEW[current.review_status].tone}>{REVIEW[current.review_status].label}</Badge>
          </div>
          {vlmLine(current) ? <p className="text-xs text-muted">{vlmLine(current)}</p> : null}
          <ConfidenceBasis finding={current} />
          <FieldLinks finding={current} />
          <History comparisonId={comparisonId} findingId={current.id} />
          {canReview ? <ReviewForm key={current.id} comparisonId={comparisonId} finding={current} />
            : <p className="text-xs text-muted">Your role can read but not review differences.</p>}
        </article>
      ) : (
        <p className="text-xs text-muted">Select a difference to see its evidence and review it.</p>
      )}
    </div>
  );
}

function ConfidenceBasis({ finding }: { finding: ComparisonFindingOut }) {
  const basis = finding.metrics["confidence_basis"];
  if (!Array.isArray(basis) || basis.length === 0) return null;
  return (
    <details className="text-xs">
      <summary className="cursor-pointer text-muted">How the evidence confidence was measured</summary>
      <ul className="mt-1 list-disc pl-4">{basis.map((b) => <li key={String(b)}>{String(b)}</li>)}</ul>
    </details>
  );
}

function FieldLinks({ finding }: { finding: ComparisonFindingOut }) {
  const fields = finding.metrics["extracted_fields"];
  if (!Array.isArray(fields) || fields.length === 0) return null;
  return (
    <p className="text-xs">
      <span className="text-muted">Overlapping extracted fields: </span>
      {(fields as { id: string; document: string; name: string; value: string | null }[])
        .map((f) => `${f.document} ${String(f.name).replace(/_/g, " ")} = ${f.value ?? "-"}`).join("; ")}
    </p>
  );
}
