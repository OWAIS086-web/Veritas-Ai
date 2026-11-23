"""The comparison engine: rasterize and register both documents page by page, compare their
text and pixels, fuse the evidence, check the strongest regions with the vision model, and
return numbered findings with validated regions plus a summary of how they were measured.

The engine has no database access. The CPU-heavy steps run in a thread; the vision-model calls
are awaited. Every region is clipped to its page before it leaves the engine.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.models.doccompare import COMPARISON_LIMITATION
from app.services.doccompare import text as text_cmp
from app.services.doccompare import visual
from app.services.doccompare.fusion import Candidate, fuse, score
from app.services.doccompare.geometry import clip, overlaps, valid
from app.services.doccompare.pages import PagePair, page_sizes, pair_pages, rasters
from app.services.doccompare.vision import Vision, pick_for_assessment
from app.services.parsing.model import Line

Progress = Callable[[str, int], Awaitable[None]]
LIMITATIONS = [
    COMPARISON_LIMITATION,
    "Regions are located from changed pixels and text boxes after automatic alignment; a "
    "poorly aligned page (low page similarity) gives lower evidence confidence.",
    "Text from OCR can misread characters; letter-only OCR differences below the similarity "
    "threshold are treated as noise and not reported.",
    "The vision model only adjusts confidence or proposes regions that changed pixels confirm; "
    "it never creates a finding on its own and its boxes are validated before use.",
]


@dataclass(frozen=True)
class DocInput:
    """One side of the comparison: the stored bytes plus what the pipeline extracted."""

    document_id: str
    filename: str
    data: bytes
    mime: str
    sha256: str
    pages: list[dict[str, Any]]  # document_pages rows: page_number, method, lines
    fields: list[dict[str, Any]]  # extracted fields: id, name, value, value_type, page, bbox


@dataclass(frozen=True)
class EngineSettings:
    dpi: int
    max_pages: int
    work_width: int
    ssim_threshold: float
    vlm_max_regions: int
    vlm_max_pages: int


@dataclass
class EngineResult:
    findings: list[Candidate]
    summary: dict[str, Any]
    vlm: dict[str, Any] | None = None


@dataclass
class _Prepared:
    pairs: list[PagePair]
    masks: dict[int, np.ndarray]
    candidates: list[Candidate]
    pages: list[dict[str, Any]]
    original_pages: int
    test_pages: int
    original_sizes: list[tuple[float, float]] = field(default_factory=list)
    test_sizes: list[tuple[float, float]] = field(default_factory=list)


def _lines(doc: DocInput, page: int) -> tuple[list[Line], str | None]:
    row = next((p for p in doc.pages if p.get("page_number") == page), None)
    if row is None:
        return [], None
    lines = [Line.from_json(ln) for ln in row.get("lines") or [] if isinstance(ln, dict)]
    return lines, str(row.get("method") or "ocr")


def _page_changes(
    o_count: int, t_count: int, o_sizes: list[Any], t_sizes: list[Any]
) -> list[Candidate]:
    """Pages beyond the shorter document: added on the test side or removed from it."""
    out: list[Candidate] = []
    for page in range(o_count + 1, t_count + 1):
        w, h = t_sizes[page - 1]
        out.append(
            Candidate(
                type="page_added",
                test_page=page,
                original_page=None,
                region=clip([0.0, 0.0, w, h], w, h),
                original_region=None,
                sources=["page"],
            )
        )
    for page in range(t_count + 1, o_count + 1):
        w, h = o_sizes[page - 1]
        out.append(
            Candidate(
                type="page_removed",
                test_page=None,
                original_page=page,
                region=None,
                original_region=clip([0.0, 0.0, w, h], w, h),
                sources=["page"],
            )
        )
    return out


def _prepare(original: DocInput, test: DocInput, cfg: EngineSettings) -> _Prepared:
    o_rasters = rasters(original.data, original.mime, cfg.dpi, cfg.max_pages)
    t_rasters = rasters(test.data, test.mime, cfg.dpi, cfg.max_pages)
    o_sizes = page_sizes(original.data, original.mime, o_rasters)
    t_sizes = page_sizes(test.data, test.mime, t_rasters)
    pairs = pair_pages(o_rasters, o_sizes, t_rasters, t_sizes, cfg.work_width)
    page_map = {p.test_page: p.original_page for p in pairs}
    candidates: list[Candidate] = []
    masks: dict[int, np.ndarray] = {}
    page_rows: list[dict[str, Any]] = []
    for pair in pairs:
        regions, changed = visual.detect(pair, cfg.ssim_threshold)
        masks[pair.test_page] = changed
        o_lines, o_method = _lines(original, pair.original_page)
        t_lines, t_method = _lines(test, pair.test_page)
        # Without text on both sides a text comparison would report everything as added or
        # removed; the page is then compared by pixels only.
        text_compared = bool(o_lines and t_lines)
        texts = (
            text_cmp.compare_page(pair, o_lines, t_lines, o_method or "ocr", t_method or "ocr")
            if text_compared
            else []
        )
        candidates.extend(fuse(texts, regions, page_map))
        page_rows.append(
            {
                "test_page": pair.test_page,
                "original_page": pair.original_page,
                "alignment": pair.registration.method,
                "page_ssim": round(pair.registration.ssim, 3),
                "changed_share": round(float(changed[pair.valid_mask].mean()), 4)
                if pair.valid_mask.any()
                else None,
                "text_compared": text_compared,
                "original_text_method": o_method,
                "test_text_method": t_method,
                "visual_regions": len(regions),
                "text_changes": len(texts),
            }
        )
    candidates.extend(_page_changes(len(o_rasters), len(t_rasters), o_sizes, t_sizes))
    return _Prepared(
        pairs, masks, candidates, page_rows, len(o_rasters), len(t_rasters), o_sizes, t_sizes
    )


def _field_ref(f: dict[str, Any], side: str) -> dict[str, Any]:
    return {
        "id": str(f["id"]),
        "document": side,
        "name": f.get("name"),
        "value": f.get("value"),
        "value_type": f.get("value_type"),
        "page": f.get("page_number"),
    }


def attach_fields(c: Candidate, original: DocInput, test: DocInput) -> None:
    """The extracted fields (real `extracted_fields` rows) whose boxes the finding overlaps."""
    refs: list[dict[str, Any]] = []
    for side, doc, page, region in (
        ("test", test, c.test_page, c.region),
        ("original", original, c.original_page, c.original_region),
    ):
        if page is None or region is None or c.type.startswith("page_"):
            continue
        for f in doc.fields:
            box = f.get("bbox")
            if (
                f.get("page_number") == page
                and isinstance(box, list)
                and valid(box)
                and overlaps([float(v) for v in box], region)
            ):
                refs.append(_field_ref(f, side))
    c.fields = refs


def _order(c: Candidate) -> tuple[float, ...]:
    if c.test_page is None:  # removed pages go last, in the original's order
        return (1e9, float(c.original_page or 0), 0.0, 0.0)
    region = c.region or [0.0, 0.0, 0.0, 0.0]
    return (float(c.test_page), round(region[1] / 4), region[0], region[1])


def _vlm_status(vision: Vision) -> str:
    st = vision.stats
    if st.calls == 0:
        return "failed" if st.errors else "not_run"
    return "used"


async def run(
    original: DocInput,
    test: DocInput,
    cfg: EngineSettings,
    vision: Vision | None,
    progress: Progress,
) -> EngineResult:
    await progress("aligning_pages", 15)
    prep = await asyncio.to_thread(_prepare, original, test, cfg)
    ssim_by_page = {p.test_page: p.registration.ssim for p in prep.pairs}
    for c in prep.candidates:
        attach_fields(c, original, test)
        score(c, ssim_by_page.get(c.test_page or -1))
    await progress("vision_analysis", 60)
    if vision is not None and prep.pairs:
        by_page = {p.test_page: p for p in prep.pairs}
        for c in pick_for_assessment(prep.candidates, cfg.vlm_max_regions):
            if c.test_page is None:
                continue
            await vision.assess(by_page[c.test_page], c)
            if vision.stats.calls == 0 and vision.stats.errors:
                break  # the model is unreachable; don't wait on every remaining region
        if not (vision.stats.calls == 0 and vision.stats.errors):
            for pair in prep.pairs[: cfg.vlm_max_pages]:
                await vision.scan_page(pair, prep.masks[pair.test_page], prep.candidates)
        vision.stats.status = _vlm_status(vision)
        for c in prep.candidates:
            attach_fields(c, original, test)
            score(c, ssim_by_page.get(c.test_page or -1))
    await progress("saving_findings", 85)
    findings = sorted(prep.candidates, key=_order)
    counts: dict[str, dict[str, int]] = {"type": {}, "severity": {}}
    for c in findings:
        counts["type"][c.type] = counts["type"].get(c.type, 0) + 1
        counts["severity"][c.severity] = counts["severity"].get(c.severity, 0) + 1
    summary = {
        "original": {
            "document_id": original.document_id,
            "filename": original.filename,
            "sha256": original.sha256,
            "mime_type": original.mime,
            "pages_compared": prep.original_pages,
        },
        "test": {
            "document_id": test.document_id,
            "filename": test.filename,
            "sha256": test.sha256,
            "mime_type": test.mime,
            "pages_compared": prep.test_pages,
        },
        "page_limit": cfg.max_pages,
        "pages": prep.pages,
        "findings": len(findings),
        "by_type": counts["type"],
        "by_severity": counts["severity"],
        "method": {
            "dpi": cfg.dpi,
            "work_width": cfg.work_width,
            "ssim_threshold": cfg.ssim_threshold,
            "gray_diff": visual.GRAY_DIFF,
            "min_changed_pixels": visual.MIN_AREA,
            "region_ssim_max": visual.REGION_SSIM_MAX,
            "ocr_similarity": text_cmp.OCR_SIMILARITY,
        },
        "limitations": LIMITATIONS,
    }
    vlm = vision.stats.to_json() if vision is not None else None
    if vlm is not None:
        summary["vlm"] = vlm
    return EngineResult(findings=findings, summary=summary, vlm=vlm)
