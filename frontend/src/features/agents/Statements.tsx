import { Link } from "react-router-dom";

/** A citation as stored by the backend (every one resolved to a real row). */
export interface Ref {
  document_id?: string;
  page?: number;
  field_id?: string;
  finding_id?: string;
  entity_id?: string;
  relationship_id?: string;
  anomaly_id?: string;
}

export interface StatementData {
  text: string;
  refs?: Ref[];
  supported?: boolean;
}

function refLabel(r: Ref): string {
  if (r.finding_id) return "Finding";
  if (r.document_id) return r.page ? `Document, page ${r.page}` : "Document";
  if (r.entity_id) return "Entity";
  if (r.relationship_id) return "Relationship";
  if (r.anomaly_id) return "Forensic anomaly";
  return "Field";
}

function refHref(r: Ref, caseId: string): string | null {
  if (r.finding_id) return `/findings/${r.finding_id}`;
  if (r.document_id) return `/documents/${r.document_id}${r.field_id ? `?field=${r.field_id}` : ""}`;
  if (r.entity_id || r.relationship_id) return `/graph?case=${caseId}`;
  return null;
}

export function Citations({ refs, caseId }: { refs: Ref[]; caseId: string }) {
  if (refs.length === 0) return null;
  return (
    <span className="ml-1 inline-flex flex-wrap gap-1 align-middle">
      {refs.map((r, i) => {
        const href = refHref(r, caseId);
        const label = refLabel(r);
        return href ? (
          <Link key={i} to={href} className="rounded border border-evidence/30 px-1.5 text-[11px] text-evidence hover:bg-evidence/10">
            {label}
          </Link>
        ) : (
          <span key={i} className="rounded border border-line px-1.5 text-[11px] text-muted">{label}</span>
        );
      })}
    </span>
  );
}

export function Statements({ items, caseId, label }: { items: StatementData[]; caseId: string; label: string }) {
  if (items.length === 0) return <p className="text-sm text-muted">None reported.</p>;
  return (
    <ul className="space-y-1.5 text-sm" aria-label={label}>
      {items.map((s, i) => (
        <li key={i}>
          {s.text}
          <Citations refs={s.refs ?? []} caseId={caseId} />
          {s.supported === false ? (
            <span className="ml-1 text-[11px] text-warning">(citation removed: not found in this case)</span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
