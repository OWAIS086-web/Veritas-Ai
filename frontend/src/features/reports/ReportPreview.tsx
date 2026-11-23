import { Link } from "react-router-dom";

import { Badge, Card, CardTitle, Mono } from "@/components/ui/primitives";

/** The subset of the report model the preview reads (the API returns the full model). */
interface Citation {
  finding_id: string | null;
  document_id: string;
  filename: string;
  page: number | null;
  field_id: string | null;
  field_name: string;
  value: string | null;
  role: string | null;
}
interface Discrepancy {
  finding_id: string;
  title: string;
  severity: string;
  priority: string;
  review_label: string;
  evidence: Citation[];
}
export interface ReportModelView {
  title: string;
  label: string | null;
  executive_summary: string;
  scope: { documents: number; findings: number };
  identified_discrepancies: Discrepancy[];
  evidence_references: Citation[];
  forensic_observations: { anomaly_id: string; filename: string; type: string; page: number | null }[];
  missing_supporting_documents: { text: string; source: string }[];
  alternative_explanations: { finding_id: string; text: string }[];
  limitations: string[];
  audit: { generated_by: string | null; generated_at: string; summary_method: string; summary_note: string | null };
}

export function ReportPreview({ model }: { model: ReportModelView }) {
  return (
    <div className="space-y-4">
      <Card>
        {model.label ? <p className="mb-2 text-xs font-semibold text-warning">{model.label}</p> : null}
        <CardTitle>{model.title}</CardTitle>
        <h3 className="mb-1 text-xs uppercase tracking-wider text-muted">Executive summary</h3>
        <p className="text-sm">{model.executive_summary}</p>
        <p className="mt-2 text-xs text-muted">
          Summary: {model.audit.summary_method === "template" ? "built from the counts in this report" : "written by the investigation model and verified"}.
          {model.audit.summary_note ? ` ${model.audit.summary_note}` : ""}
        </p>
      </Card>
      <Card>
        <CardTitle>Identified discrepancies</CardTitle>
        {model.identified_discrepancies.length === 0 ? <p className="text-sm text-muted">None.</p> : (
          <ul className="space-y-3" aria-label="Report discrepancies">
            {model.identified_discrepancies.map((d) => (
              <li key={d.finding_id} className="text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Link to={`/findings/${d.finding_id}`} className="font-medium hover:text-evidence">{d.title}</Link>
                  <Badge tone={d.review_label === "Not yet reviewed" ? "warning" : "neutral"}>{d.review_label}</Badge>
                </div>
                <p className="text-xs text-muted">Severity {d.severity}, priority {d.priority}, {d.evidence.length} evidence item(s).</p>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card className="overflow-x-auto p-0">
        <div className="p-5 pb-0"><CardTitle>Evidence references</CardTitle></div>
        <table className="w-full text-left text-xs" aria-label="Report evidence references">
          <thead className="border-b border-line uppercase tracking-wider text-muted">
            <tr>
              <th scope="col" className="px-4 py-2 font-medium">Document</th>
              <th scope="col" className="px-4 py-2 font-medium">Page</th>
              <th scope="col" className="px-4 py-2 font-medium">Field</th>
              <th scope="col" className="px-4 py-2 font-medium">Value</th>
              <th scope="col" className="px-4 py-2 font-medium">Role</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {model.evidence_references.map((c, i) => (
              <tr key={i}>
                <td className="px-4 py-1.5">
                  <Link to={`/documents/${c.document_id}${c.field_id ? `?field=${c.field_id}` : ""}`} className="text-evidence hover:underline">
                    {c.filename}
                  </Link>
                </td>
                <td className="px-4 py-1.5 tabular">{c.page ?? "n/a"}</td>
                <td className="px-4 py-1.5">{c.field_name}</td>
                <td className="px-4 py-1.5"><Mono>{c.value}</Mono></td>
                <td className="px-4 py-1.5">{c.role}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardTitle>Alternative explanations</CardTitle>
          {model.alternative_explanations.length === 0 ? (
            <p className="text-sm text-muted">None recorded. They come from an approved investigation.</p>
          ) : (
            <ul className="list-disc space-y-1 pl-4 text-sm" aria-label="Report hypotheses">
              {model.alternative_explanations.map((h, i) => <li key={i}><Badge>Hypothesis</Badge> {h.text}</li>)}
            </ul>
          )}
        </Card>
        <Card>
          <CardTitle>Missing supporting documents</CardTitle>
          {model.missing_supporting_documents.length === 0 ? <p className="text-sm text-muted">None.</p> : (
            <ul className="space-y-1 text-sm">
              {model.missing_supporting_documents.map((x, i) => <li key={i}>{x.text}</li>)}
            </ul>
          )}
        </Card>
      </div>
      <Card>
        <CardTitle>Limitations</CardTitle>
        <ul className="list-disc space-y-1 pl-4 text-xs text-muted" aria-label="Report limitations">
          {model.limitations.map((l) => <li key={l}>{l}</li>)}
        </ul>
      </Card>
    </div>
  );
}
