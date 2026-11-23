"""PDF structure: metadata, incremental revisions, fonts, images, forms and signatures.

Observations only. An incremental update or a second producer is normal for signed or
form-filled files; it is reported so a reviewer can look, not as a sign of alteration.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any

import pymupdf

from app.services.forensics.model import (
    AnalysisResult,
    Anomaly,
    FieldBox,
    overlapping_fields,
    union,
)

ANALYSIS = "pdf_structure"
_DATE = re.compile(r"^D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?")
RELEVANT_TYPES = {"amount", "reference", "quantity", "date"}
RARE_FONT_MAX_SPANS = 2


def parse_pdf_date(value: str | None) -> datetime | None:
    """PDF date strings (D:YYYYMMDDHHmmSS...) to UTC datetimes; None when unparseable."""
    if not value:
        return None
    m = _DATE.match(value.strip())
    if not m:
        return None
    y, mo, d, h, mi, s = (
        int(p) if p else default for p, default in zip(m.groups(), (0, 1, 1, 0, 0, 0), strict=True)
    )
    try:
        return datetime(y, mo, d, h, mi, s, tzinfo=UTC)
    except ValueError:
        return None


def _revisions(data: bytes) -> list[dict[str, Any]]:
    """Metadata of each saved revision: the file cut at every %%EOF marker."""
    out: list[dict[str, Any]] = []
    for match in re.finditer(rb"%%EOF", data):
        prefix = data[: match.end()]
        try:
            with pymupdf.open(stream=prefix, filetype="pdf") as rev:
                meta = rev.metadata or {}
        except Exception:
            out.append({"end": match.end(), "readable": False})
            continue
        out.append(
            {
                "end": match.end(),
                "readable": True,
                "producer": meta.get("producer") or None,
                "creator": meta.get("creator") or None,
                "modDate": meta.get("modDate") or None,
            }
        )
    return out


def _spans(doc: pymupdf.Document) -> list[dict[str, Any]]:
    spans = []
    for index in range(len(doc)):
        page = doc[index]
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span.get("text", "").strip():
                        spans.append(
                            {
                                "page": index + 1,
                                "font": span["font"],
                                "text": span["text"],
                                "bbox": [round(c, 2) for c in span["bbox"]],
                            }
                        )
    return spans


def analyze(data: bytes, fields: list[FieldBox]) -> AnalysisResult:
    result = AnalysisResult(
        ANALYSIS,
        limitations=[
            "Incremental updates and a change of producer are normal for signed, annotated or "
            "form-filled PDFs.",
            "Font checks see only the fonts named in the file; text drawn as images is not "
            "covered.",
        ],
    )
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        meta = {k: v for k, v in (doc.metadata or {}).items() if v}
        pages: list[dict[str, Any]] = []
        signature_fields = 0
        for index in range(len(doc)):
            page = doc[index]
            fonts = page.get_fonts(full=True)
            widgets = list(page.widgets() or [])
            signature_fields += sum(
                1 for w in widgets if w.field_type == pymupdf.PDF_WIDGET_TYPE_SIGNATURE
            )
            pages.append(
                {
                    "page": index + 1,
                    "fonts": sorted({f[3] for f in fonts}),
                    "embedded_fonts": sorted({f[3] for f in fonts if f[1] not in ("", "n/a")}),
                    "images": len(page.get_images(full=True)),
                    "annotations": sum(1 for _ in page.annots() or []),
                    "form_fields": len(widgets),
                }
            )
        spans = _spans(doc)
        is_form = bool(doc.is_form_pdf)
        encrypted = bool(doc.is_encrypted)
    revisions = _revisions(data)
    result.details = {
        "metadata": meta,
        "eof_markers": data.count(b"%%EOF"),
        "startxref_sections": data.count(b"startxref"),
        "revisions": revisions,
        "pages": pages,
        "is_form": is_form,
        "signature_fields": signature_fields,
        "encrypted": encrypted,
    }

    saves = max(result.details["eof_markers"], result.details["startxref_sections"])
    if saves > 1:
        result.anomalies.append(
            Anomaly(
                "incremental_update",
                "low",
                f"The file was saved {saves} times: {saves - 1} incremental update(s) were "
                "appended after the first version. Signing, annotating and form filling also "
                "do this.",
                metrics={"saves": saves},
            )
        )
    producers = [r["producer"] for r in revisions if r.get("readable") and r.get("producer")]
    if len(set(producers)) > 1:
        result.anomalies.append(
            Anomaly(
                "metadata_inconsistency",
                "medium",
                "The revisions of the file record different producing software: "
                + " → ".join(dict.fromkeys(producers))
                + ".",
                metrics={"producers": producers},
            )
        )
    created, modified = (
        parse_pdf_date(meta.get("creationDate")),
        parse_pdf_date(meta.get("modDate")),
    )
    if created and modified and modified < created:
        result.anomalies.append(
            Anomaly(
                "metadata_inconsistency",
                "low",
                f"The modification date ({modified:%Y-%m-%d %H:%M}) is earlier than the creation "
                f"date ({created:%Y-%m-%d %H:%M}).",
                metrics={"creationDate": meta.get("creationDate"), "modDate": meta.get("modDate")},
            )
        )

    # A font used only for one or two pieces of text, over an amount or a reference.
    usage = Counter(s["font"] for s in spans)
    common = [f for f, n in usage.items() if n > RARE_FONT_MAX_SPANS]
    relevant = [f for f in fields if f.value_type in RELEVANT_TYPES]
    if common:
        for span in spans:
            if usage[span["font"]] > RARE_FONT_MAX_SPANS:
                continue
            for hit in overlapping_fields(relevant, span["page"], span["bbox"]):
                result.anomalies.append(
                    Anomaly(
                        "font_inconsistency",
                        "medium",
                        f"The {hit.name.replace('_', ' ')} on page {span['page']} is set in "
                        f'"{span["font"]}", a font used nowhere else in the document (the rest '
                        f"uses {', '.join(sorted(common))}).",
                        page_number=span["page"],
                        region=union(span["bbox"], list(hit.bbox)),
                        metrics={
                            "font": span["font"],
                            "field": hit.name,
                            "field_id": hit.field_id,
                            "font_spans": usage[span["font"]],
                        },
                    )
                )
    result.details["fonts_by_spans"] = dict(usage)
    return result
