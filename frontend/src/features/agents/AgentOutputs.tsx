import { Badge } from "@/components/ui/primitives";
import { Citations, Statements, type StatementData } from "@/features/agents/Statements";

type Out = Record<string, unknown>;

const list = <T,>(value: unknown): T[] => (Array.isArray(value) ? (value as T[]) : []);

interface Assessment {
  finding_id: string;
  summary?: string;
  supporting?: StatementData[];
  conflicting?: StatementData[];
}

interface RiskItem {
  finding_id: string;
  assessed: boolean;
  evidence_strength?: string;
  review_urgency?: string;
  uncertainty: string;
  alternative_explanations: { text: string; hypothesis: boolean }[];
  persisted_scores: Record<string, string | null>;
}

interface Missing {
  text: string;
  document_types?: string[];
  source: "model" | "rule";
  finding_id?: string;
}

function Sub({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-3">
      <h4 className="mb-1 text-xs font-medium uppercase tracking-wider text-muted">{title}</h4>
      {children}
    </div>
  );
}

function RiskView({ out, caseId }: { out: Out; caseId: string }) {
  const items = list<RiskItem>(out.assessments);
  return (
    <ul className="space-y-3" aria-label="Risk assessments">
      {items.map((a) => (
        <li key={a.finding_id} className="rounded-lg border border-line p-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <Citations refs={[{ finding_id: a.finding_id }]} caseId={caseId} />
            {a.assessed ? (
              <>
                <Badge tone={a.evidence_strength === "strong" ? "primary" : "neutral"}>Evidence: {a.evidence_strength}</Badge>
                <Badge tone={a.review_urgency === "high" ? "warning" : "neutral"}>Review urgency: {a.review_urgency}</Badge>
              </>
            ) : (
              <Badge tone="warning">Not assessed by the model</Badge>
            )}
          </div>
          <p className="mt-2 text-xs text-muted">
            Stored scores (unchanged): anomaly score {a.persisted_scores.anomaly_score ?? "n/a"}, evidence confidence{" "}
            {a.persisted_scores.evidence_confidence ?? "not measured"}, priority {a.persisted_scores.priority}.
          </p>
          <p className="mt-2">{a.uncertainty}</p>
          {a.alternative_explanations.length > 0 ? (
            <Sub title="Alternative explanations">
              <ul className="list-disc space-y-1 pl-4">
                {a.alternative_explanations.map((h, i) => (
                  <li key={i}><Badge tone="neutral">Hypothesis</Badge> {h.text}</li>
                ))}
              </ul>
            </Sub>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function CrossReferenceView({ out, caseId }: { out: Out; caseId: string }) {
  return (
    <>
      {list<Assessment>(out.assessments).map((a) => (
        <div key={a.finding_id} className="mb-3 rounded-lg border border-line p-3 text-sm">
          <p>{a.summary}<Citations refs={[{ finding_id: a.finding_id }]} caseId={caseId} /></p>
          <Sub title="Supporting"><Statements items={a.supporting ?? []} caseId={caseId} label="Supporting evidence" /></Sub>
          <Sub title="Conflicting"><Statements items={a.conflicting ?? []} caseId={caseId} label="Conflicting evidence" /></Sub>
        </div>
      ))}
      <Sub title="Missing information">
        <ul className="space-y-1 text-sm" aria-label="Missing information">
          {list<Missing>(out.missing_information).map((m, i) => (
            <li key={i}>
              {m.text}
              {m.document_types?.length ? <span className="text-muted"> ({m.document_types.join(", ")})</span> : null}{" "}
              <Badge>{m.source === "rule" ? "Detected by a comparison rule" : "Suggested by the agent"}</Badge>
            </li>
          ))}
        </ul>
      </Sub>
    </>
  );
}

/** One agent's validated, persisted output. */
export function AgentOutput({ agent, out, caseId }: { agent: string; out: Out; caseId: string }) {
  if (out.failed) return <p className="text-sm text-danger">This step failed: {String(out.error)}</p>;
  switch (agent) {
    case "planner":
      return (
        <>
          <p className="text-sm">{String(out.focus ?? "")}</p>
          <Sub title="Questions"><Statements items={list(out.questions)} caseId={caseId} label="Questions" /></Sub>
        </>
      );
    case "document":
      return (
        <ul className="space-y-2" aria-label="Document summaries">
          {list<{ document_id: string; summary: string; facts: StatementData[] }>(out.documents).map((d) => (
            <li key={d.document_id} className="text-sm">
              {d.summary}<Citations refs={[{ document_id: d.document_id }]} caseId={caseId} />
              <Statements items={d.facts} caseId={caseId} label="Document facts" />
            </li>
          ))}
        </ul>
      );
    case "forensics":
      return (
        <>
          <p className="text-sm">{String(out.summary ?? "")}</p>
          <Sub title="Observations"><Statements items={list(out.observations)} caseId={caseId} label="Forensic observations" /></Sub>
          <Sub title="Limitations">
            <ul className="list-disc pl-4 text-xs text-muted">{list<string>(out.limitations).map((l) => <li key={l}>{l}</li>)}</ul>
          </Sub>
        </>
      );
    case "cross_reference":
      return <CrossReferenceView out={out} caseId={caseId} />;
    case "entity":
    case "graph":
      return <Statements items={list(out.observations)} caseId={caseId} label={`${agent} observations`} />;
    case "risk":
      return <RiskView out={out} caseId={caseId} />;
    case "report":
      return (
        <>
          <p className="text-sm">{String(out.executive_summary ?? "")}</p>
          {out.summary_status === "rejected" ? (
            <p className="mt-1 text-xs text-warning">
              The model's summary named values not found in the investigation ({list<string>(out.unverified_tokens).join(", ")}),
              so a factual summary was used instead.
            </p>
          ) : null}
          <Sub title="Recommended human review"><Statements items={list(out.recommended_review)} caseId={caseId} label="Recommended review" /></Sub>
        </>
      );
    default:
      return null;
  }
}
