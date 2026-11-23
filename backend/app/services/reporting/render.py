"""Renderers. All four formats are produced from the same `ReportModel` through one layout
(`layout()`: headed sections of paragraphs and tables), so they always carry the same content
and citations. PDF uses PyMuPDF's HTML layout (`Story`), already a dependency, instead of
adding ReportLab."""

from __future__ import annotations

import html
import io
from dataclasses import dataclass, field

from docx import Document as DocxDocument
from openpyxl import Workbook

from app.integrations.pdf.story import render_story, soft_break
from app.services.reporting.model import SECTIONS, ReportModel

MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "json": "application/json",
}
HEADINGS = dict(SECTIONS)


@dataclass
class Table:
    headers: list[str]
    rows: list[list[str]]


@dataclass
class Section:
    key: str
    title: str
    paragraphs: list[str] = field(default_factory=list)
    table: Table | None = None


def _s(value: object) -> str:
    return "" if value is None else str(value)


def _page(page: int | None) -> str:
    return "n/a" if page is None else str(page)


def layout(r: ReportModel) -> list[Section]:
    none = "None."
    a = r.audit
    sections = [
        Section("executive_summary", HEADINGS["executive_summary"], [r.executive_summary]),
        Section(
            "scope",
            HEADINGS["scope"],
            [
                f"Case: {r.scope.case_title} ({r.scope.investigation_type}).",
                f"Objective: {r.objective or r.scope.objective or 'not stated'}.",
                f"{r.scope.documents} document(s) and {r.scope.findings} finding(s) are in scope.",
            ],
        ),
        Section(
            "documents_analyzed",
            HEADINGS["documents_analyzed"],
            table=Table(
                ["Document", "Document id", "Type", "Pages", "Status", "SHA-256"],
                [
                    [
                        d.filename,
                        str(d.document_id),
                        _s(d.doc_type),
                        _s(d.pages),
                        d.status,
                        d.sha256,
                    ]
                    for d in r.documents_analyzed
                ],
            ),
        ),
        Section(
            "entities_identified",
            HEADINGS["entities_identified"],
            [] if r.entities_identified else [none],
            Table(
                ["Name", "Type", "Mentions", "Status", "Entity id"],
                [
                    [e.name, e.type, str(e.mentions), e.status, str(e.entity_id)]
                    for e in r.entities_identified
                ],
            )
            if r.entities_identified
            else None,
        ),
        Section(
            "extracted_information",
            HEADINGS["extracted_information"],
            table=Table(
                ["Document", "Field", "Value", "Page", "Method", "Confidence"],
                [
                    [d.filename, f.name, _s(f.value), _page(f.page), f.method, _s(f.confidence)]
                    for d in r.extracted_information
                    for f in d.fields
                ],
            ),
        ),
        Section(
            "identified_discrepancies",
            HEADINGS["identified_discrepancies"],
            [
                f"{d.title} (finding {d.finding_id}). "
                f"Severity {d.severity}, priority {d.priority}, "
                f"anomaly score {d.anomaly_score or 'n/a'}, evidence confidence "
                f"{d.evidence_confidence or 'not measured'}. Review status: {d.review_label}. "
                f"{d.explanation}"
                for d in r.identified_discrepancies
            ]
            or [none],
        ),
        Section(
            "forensic_observations",
            HEADINGS["forensic_observations"],
            []
            if r.forensic_observations
            else ["No forensic anomaly was recorded for these documents."],
            Table(
                ["Document", "Observation", "Severity", "Page", "Explanation"],
                [
                    [o.filename, o.type, o.severity, _page(o.page), o.explanation]
                    for o in r.forensic_observations
                ],
            )
            if r.forensic_observations
            else None,
        ),
        Section(
            "evidence_references",
            HEADINGS["evidence_references"],
            [] if r.evidence_references else [none],
            Table(
                ["Finding id", "Document", "Document id", "Page", "Field", "Value", "Role"],
                [
                    [
                        _s(c.finding_id),
                        c.filename,
                        str(c.document_id),
                        _page(c.page),
                        c.field_name,
                        _s(c.value),
                        _s(c.role),
                    ]
                    for c in r.evidence_references
                ],
            )
            if r.evidence_references
            else None,
        ),
        Section(
            "relationship_analysis",
            HEADINGS["relationship_analysis"],
            [] if r.relationship_analysis else [none],
            Table(
                ["From", "Relationship", "To", "Finding id", "Evidence items"],
                [
                    [x.source, x.type, x.target, _s(x.finding_id), str(x.evidence_count)]
                    for x in r.relationship_analysis
                ],
            )
            if r.relationship_analysis
            else None,
        ),
        Section(
            "missing_supporting_documents",
            HEADINGS["missing_supporting_documents"],
            [
                f"{x.text} (source: {x.source.replace('_', ' ')}"
                + (f", finding {x.finding_id})" if x.finding_id else ")")
                for x in r.missing_supporting_documents
            ]
            or [none],
        ),
        Section(
            "alternative_explanations",
            HEADINGS["alternative_explanations"],
            [f"Hypothesis (finding {h.finding_id}): {h.text}" for h in r.alternative_explanations]
            or [
                "No alternative explanation was recorded. "
                "Run and approve an investigation to add them."
            ],
        ),
        Section(
            "recommended_human_review",
            HEADINGS["recommended_human_review"],
            [
                x.text + (f" (finding {x.finding_id})" if x.finding_id else "")
                for x in r.recommended_human_review
            ]
            or [none],
        ),
        Section("limitations", HEADINGS["limitations"], list(r.limitations)),
        Section(
            "audit",
            HEADINGS["audit"],
            [
                f"Report id: {a.report_id}. Generated {a.generated_at:%Y-%m-%d %H:%M} UTC by "
                f"{a.generated_by or 'a former member'}.",
                f"Investigation: {a.investigation_id or 'none'}"
                + (
                    f", approved by {a.investigation_approved_by or 'a former member'} on "
                    f"{a.investigation_approved_at:%Y-%m-%d %H:%M} UTC."
                    if a.investigation_approved_at
                    else "."
                ),
                f"Executive summary: {a.summary_method.replace('_', ' ')}."
                + (f" {a.summary_note}" if a.summary_note else ""),
                f"Pipeline versions: {', '.join(a.pipeline_versions) or 'n/a'}.",
            ],
        ),
    ]
    return sections


def _header(r: ReportModel) -> list[str]:
    lines = [f"Investigation id: {r.investigation_id or 'none'}", f"Organization: {r.organization}"]
    if r.label:
        lines.insert(0, r.label)
    return lines


def render_json(r: ReportModel) -> bytes:
    return r.model_dump_json(indent=2).encode("utf-8")


def render_docx(r: ReportModel) -> bytes:
    doc = DocxDocument()
    doc.add_heading(r.title, level=0)
    for line in _header(r):
        doc.add_paragraph(line)
    for sec in layout(r):
        doc.add_heading(sec.title, level=1)
        for p in sec.paragraphs:
            doc.add_paragraph(p)
        if sec.table and sec.table.rows:
            t = doc.add_table(rows=1, cols=len(sec.table.headers))
            t.style = "Table Grid"
            for cell, text in zip(t.rows[0].cells, sec.table.headers, strict=True):
                cell.text = text
            for row in sec.table.rows:
                cells = t.add_row().cells
                for cell, text in zip(cells, row, strict=True):
                    cell.text = text
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def render_xlsx(r: ReportModel) -> bytes:
    wb = Workbook()
    summary = wb.active
    summary.title = "Report"
    summary.append([r.title])
    for line in _header(r):
        summary.append([line])
    for sec in layout(r):
        summary.append([])
        summary.append([sec.title])
        for p in sec.paragraphs:
            summary.append([p])
        if sec.table and sec.table.rows:
            # One sheet per tabular section (sheet names are limited to 31 characters).
            ws = wb.create_sheet(sec.title[:31])
            ws.append(sec.table.headers)
            for row in sec.table.rows:
                ws.append(row)
            summary.append([f"See sheet '{ws.title}' ({len(sec.table.rows)} rows)."])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


CSS = """
body { font-family: sans-serif; font-size: 9pt; }
h1 { font-size: 16pt; } h2 { font-size: 12pt; margin-top: 10pt; }
table { border-collapse: collapse; width: 100%; }
td, th { border: 0.5pt solid #888888; padding: 2pt; font-size: 7pt; vertical-align: top; }
th { background-color: #e8e8e8; }
.label { color: #b45309; font-weight: bold; }
"""


def _html(r: ReportModel) -> str:
    def e(text: str) -> str:
        # Long unbroken values (SHA-256) may wrap; escaping comes after so entities stay whole.
        return html.escape(soft_break(text))

    parts = [f"<h1>{e(r.title)}</h1>"]
    for i, line in enumerate(_header(r)):
        cls = ' class="label"' if r.label and i == 0 else ""
        parts.append(f"<p{cls}>{e(line)}</p>")
    for sec in layout(r):
        parts.append(f"<h2>{e(sec.title)}</h2>")
        parts += [f"<p>{e(p)}</p>" for p in sec.paragraphs]
        if sec.table and sec.table.rows:
            head = "".join(f"<th>{e(h)}</th>" for h in sec.table.headers)
            body = "".join(
                "<tr>" + "".join(f"<td>{e(c)}</td>" for c in row) + "</tr>"
                for row in sec.table.rows
            )
            parts.append(f"<table><tr>{head}</tr>{body}</table>")
    return "".join(parts)


def render_pdf(r: ReportModel) -> bytes:
    # 0.5 in margins; fails with StoryLayoutError instead of looping on a layout that can't end.
    return render_story(_html(r), CSS, margin=36)


RENDERERS = {"pdf": render_pdf, "docx": render_docx, "xlsx": render_xlsx, "json": render_json}


def render(r: ReportModel, fmt: str) -> bytes:
    return RENDERERS[fmt](r)
