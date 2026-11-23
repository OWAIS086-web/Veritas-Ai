"""Each renderer opens with its own library, carries every section heading in order, and
keeps the citations (finding id, document, page, value) and the synthetic-data label."""

from __future__ import annotations

import io
import json
import uuid
from datetime import UTC, datetime

import pymupdf
import pytest
from docx import Document as DocxDocument
from openpyxl import load_workbook

from app.services.reporting import model as m
from app.services.reporting.render import MIME, layout, render

FINDING = uuid.uuid4()
DOC = uuid.uuid4()
HOSTILE = "<script>alert(1)</script> & 'quotes'"


def sample() -> m.ReportModel:
    cite = m.Citation(
        finding_id=FINDING,
        document_id=DOC,
        filename="03_customs_declaration.pdf",
        page=2,
        field_id=uuid.uuid4(),
        field_name="total_amount",
        value="USD 68,000.00",
        role="conflicting",
    )
    return m.ReportModel(
        title="Investigation report: Shipment SHIP-2049",
        report_id=uuid.uuid4(),
        investigation_id=None,
        organization="Acme Imports",
        objective="Reconcile declared values",
        executive_summary="The declared totals differ by USD 20,000.00.",
        scope=m.Scope(
            case_title="Shipment SHIP-2049",
            investigation_type="international_shipment",
            objective="Reconcile declared values",
            documents=1,
            findings=1,
        ),
        documents_analyzed=[
            m.DocumentRow(
                document_id=DOC,
                filename="03_customs_declaration.pdf",
                doc_type="customs_declaration",
                pages=2,
                sha256="ab" * 32,
                status="completed",
            )
        ],
        entities_identified=[],
        extracted_information=[],
        identified_discrepancies=[
            m.Discrepancy(
                finding_id=FINDING,
                type="financial_discrepancy",
                title="Declared totals differ by USD 20,000.00",
                severity="high",
                priority="high",
                anomaly_score="0.294",
                evidence_confidence="1.000",
                explanation=f"Explanation with {HOSTILE}",
                review_status="new",
                review_label=m.NOT_REVIEWED,
                evidence=[cite],
                limitations=[],
            )
        ],
        forensic_observations=[],
        evidence_references=[cite],
        relationship_analysis=[],
        missing_supporting_documents=[],
        alternative_explanations=[m.Hypothesis(finding_id=FINDING, text="CIF vs FOB valuation.")],
        recommended_human_review=[],
        limitations=["A limitation."],
        audit=m.Audit(
            report_id=uuid.uuid4(),
            generated_at=datetime(2026, 11, 23, 12, 0, tzinfo=UTC),
            generated_by="ana@example.com",
            investigation_id=None,
            investigation_approved_by=None,
            investigation_approved_at=None,
            pipeline_versions=["2"],
            summary_method="template",
        ),
        label="SYNTHETIC DEMONSTRATION DATA",
    )


HEADINGS = [title for _, title in m.SECTIONS]


def _in_order(text: str, needles: list[str]) -> None:
    position = -1
    for needle in needles:
        found = text.find(needle, position + 1)
        assert found > position, f"{needle!r} missing or out of order"
        position = found


def test_layout_follows_the_required_section_order() -> None:
    assert [s.title for s in layout(sample())] == HEADINGS


def test_pdf_opens_and_carries_sections_citations_and_label() -> None:
    data = render(sample(), "pdf")
    # Typeset text uses ligature glyphs ("ﬁ"); extract with ligatures expanded.
    flags = pymupdf.TEXTFLAGS_TEXT & ~pymupdf.TEXT_PRESERVE_LIGATURES
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        text = " ".join(p.get_text(flags=flags) for p in doc).replace("\n", " ")
    _in_order(text, HEADINGS)
    for needle in (
        str(FINDING),
        "03_customs_declaration.pdf",
        "USD 68,000.00",
        "SYNTHETIC DEMONSTRATION DATA",
        m.NOT_REVIEWED,
    ):
        assert needle in text, needle
    assert "<script>" in text  # escaped and printed as text, not interpreted


def test_docx_opens_with_python_docx() -> None:
    doc = DocxDocument(io.BytesIO(render(sample(), "docx")))
    headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
    assert headings == HEADINGS
    cells = [c.text for t in doc.tables for row in t.rows for c in row.cells]
    assert str(FINDING) in cells and "2" in cells and "USD 68,000.00" in cells


def test_xlsx_opens_with_openpyxl_and_has_an_evidence_sheet() -> None:
    wb = load_workbook(io.BytesIO(render(sample(), "xlsx")))
    first = [row[0] for row in wb["Report"].iter_rows(values_only=True) if row and row[0]]
    _in_order("\n".join(str(x) for x in first), HEADINGS)
    rows = list(wb["Evidence references"].iter_rows(values_only=True))
    assert rows[0][:4] == ("Finding id", "Document", "Document id", "Page")
    assert rows[1][0] == str(FINDING) and rows[1][3] == "2" and rows[1][5] == "USD 68,000.00"


def test_json_round_trips_to_the_same_model() -> None:
    report = sample()
    again = m.ReportModel.model_validate(json.loads(render(report, "json")))
    assert again == report


@pytest.mark.parametrize("fmt", sorted(MIME))
def test_every_format_has_a_mime_type_and_renders(fmt: str) -> None:
    assert render(sample(), fmt)
