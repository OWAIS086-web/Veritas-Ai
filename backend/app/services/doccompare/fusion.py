"""Combine text and pixel evidence into findings, each with its sources, severity and a
deterministic evidence confidence (with the reasons that produced it).

Severity is at most `medium`: a difference between two files is an observation for review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.doccompare.geometry import Box, area, intersection, overlaps, union
from app.services.doccompare.text import TextChange
from app.services.doccompare.visual import VisualRegion

# Base evidence confidence by what supports the finding (documented on every finding).
BASE = {
    ("ocr", "cv", "text_layer"): 0.80,
    ("ocr", "cv", "ocr"): 0.70,
    ("ocr", "text_layer"): 0.60,
    ("ocr", "ocr"): 0.45,
    ("cv",): 0.40,
    ("vlm", "cv_pixels"): 0.45,
    ("page",): 0.90,
}
VLM_AGREES = 0.10
VLM_DISAGREES = -0.10
WEAK_ALIGNMENT = -0.15
WEAK_ALIGNMENT_SSIM = 0.5
RELEVANT_FIELD_TYPES = {"amount", "date", "reference", "quantity"}


@dataclass
class Candidate:
    type: str
    test_page: int | None
    original_page: int | None
    region: Box | None
    original_region: Box | None
    sources: list[str]
    original_text: str | None = None
    test_text: str | None = None
    method: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    digits_changed: bool = False
    fields: list[dict[str, Any]] = field(default_factory=list)  # overlapping extracted fields
    vlm: dict[str, Any] | None = None
    severity: str = "low"
    confidence: float = 0.0
    basis: list[str] = field(default_factory=list)
    explanation: str = ""


def _key(c: Candidate) -> tuple[Any, ...]:
    if c.type.startswith("page_"):
        return ("page",)
    if "vlm" in c.sources and "ocr" not in c.sources:
        return ("vlm", "cv_pixels")
    if "ocr" in c.sources and "cv" in c.sources:
        return ("ocr", "cv", c.method or "ocr")
    if "ocr" in c.sources:
        return ("ocr", c.method or "ocr")
    return ("cv",)


def fuse(
    texts: list[TextChange], visuals: list[VisualRegion], original_page: dict[int, int]
) -> list[Candidate]:
    """Text changes absorb the pixel regions that overlap them; the rest stay visual."""
    out: list[Candidate] = []
    used: set[int] = set()
    for t in texts:
        hits = [
            i
            for i, v in enumerate(visuals)
            if v.test_page == t.test_page and overlaps(v.region, t.region)
        ]
        used.update(hits)
        region = t.region
        if hits:
            # Pixel evidence inside the text line gives the tighter, pixel-accurate box.
            pixel = union([visuals[i].region for i in hits])
            inside = [
                max(pixel[0], t.region[0] - 2),
                max(pixel[1], t.region[1] - 2),
                min(pixel[2], t.region[2] + 2),
                min(pixel[3], t.region[3] + 2),
            ]
            if area(inside) > 0 and intersection(inside, t.region) > 0:
                region = union([inside, t.region]) if t.kind != "text_changed" else t.region
        out.append(
            Candidate(
                type=t.kind,
                test_page=t.test_page,
                original_page=original_page.get(t.test_page),
                region=region,
                original_region=t.original_region,
                sources=["ocr", "cv"] if hits else ["ocr"],
                original_text=t.original_text,
                test_text=t.test_text,
                method=t.method,
                digits_changed=t.digits_changed,
                metrics={
                    "line_text": t.line_text,
                    "original_line": t.original_line,
                    "ocr_confidence": t.confidence,
                    "local_ssim": min((visuals[i].local_ssim for i in hits), default=None),
                    "changed_pixels": sum(visuals[i].changed_pixels for i in hits),
                },
            )
        )
    for i, v in enumerate(visuals):
        if i in used:
            continue
        out.append(
            Candidate(
                type="visual_difference",
                test_page=v.test_page,
                original_page=original_page.get(v.test_page),
                region=v.region,
                original_region=v.original_region,
                sources=["cv"],
                metrics={"local_ssim": v.local_ssim, "changed_pixels": v.changed_pixels},
            )
        )
    return out


def score(c: Candidate, page_ssim: float | None) -> None:
    """Severity, evidence confidence (with its basis) and the explanation, in place."""
    key = _key(c)
    conf = BASE[key]
    c.basis = [f"{' + '.join(key)} evidence: {BASE[key]:.2f}"]
    ocr_conf = c.metrics.get("ocr_confidence")
    if isinstance(ocr_conf, float) and c.method == "ocr":
        conf *= max(0.5, ocr_conf)
        c.basis.append(f"lowest OCR confidence {ocr_conf:.2f}")
    if c.vlm and c.vlm.get("status") == "assessed":
        if c.vlm.get("visible_difference") is True:
            conf += VLM_AGREES
            c.basis.append(f"vision model sees the difference: {VLM_AGREES:+.2f}")
        elif c.vlm.get("visible_difference") is False:
            conf += VLM_DISAGREES
            c.basis.append(f"vision model sees no difference: {VLM_DISAGREES:+.2f}")
    if page_ssim is not None and page_ssim < WEAK_ALIGNMENT_SSIM and not c.type.startswith("page_"):
        conf += WEAK_ALIGNMENT
        c.basis.append(f"weak page alignment (SSIM {page_ssim:.2f}): {WEAK_ALIGNMENT:+.2f}")
    c.confidence = round(min(0.95, max(0.05, conf)), 3)

    relevant = [f for f in c.fields if f.get("value_type") in RELEVANT_FIELD_TYPES]
    if c.type.startswith("page_") or c.digits_changed or relevant:
        c.severity = "medium"
    elif c.type in ("text_changed", "text_added", "text_removed"):
        c.severity = "low"
    else:
        c.severity = "low" if (c.metrics.get("changed_pixels") or 0) >= 200 else "info"
    c.explanation = _explain(c, relevant)


def _q(text: str | None) -> str:
    return f'"{(text or "").strip()[:160]}"'


def _explain(c: Candidate, relevant: list[dict[str, Any]]) -> str:
    page = f"page {c.test_page}"
    if c.type == "text_changed":
        text = (
            f"On {page}, the test document reads {_q(c.test_text)} where the original reads "
            f"{_q(c.original_text)}"
        )
        line = c.metrics.get("line_text")
        text += f" (line {_q(line)})." if line and line != c.test_text else "."
    elif c.type == "text_added":
        text = f"On {page}, the test document has text the original doesn't: {_q(c.test_text)}."
    elif c.type == "text_removed":
        text = (
            f"On {page}, the original's text {_q(c.original_text)} has no counterpart in the "
            "test document."
        )
    elif c.type == "page_added":
        text = f"The test document has a page {c.test_page} that the original doesn't have."
    elif c.type == "page_removed":
        text = f"The original's page {c.original_page} has no counterpart in the test document."
    elif c.type == "vlm_observed_difference":
        desc = (c.vlm or {}).get("description") or "a visual difference"
        text = f"On {page}, the vision model reported {_q(desc)}, and the pixels differ there."
    else:
        ssim = c.metrics.get("local_ssim")
        text = f"On {page}, the test document's pixels differ from the original in this region" + (
            f" (local similarity {ssim:.2f})." if isinstance(ssim, float) else "."
        )
    if relevant:
        names = sorted({str(f["name"]).replace("_", " ") for f in relevant})
        text += f" It overlaps the extracted {', '.join(names)}."
    return text
