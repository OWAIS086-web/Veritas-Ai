"""Run every applicable forensic analysis on one document. Pure: bytes in, report out.

Each analysis is isolated: one that raises is recorded in `structure["errors"]`, the others
still run, and the report status becomes `partial`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.core.logging import get_logger
from app.services.forensics import pdf_structure, stamps, versions, visual
from app.services.forensics.imaging import Raster, image_rasters, pdf_rasters
from app.services.forensics.model import AnalysisResult, FieldBox, ForensicReport

logger = get_logger(__name__)
IMAGE_TYPES = {"image/png", "image/jpeg", "image/tiff"}


@dataclass(frozen=True)
class Settings:
    dpi: int
    max_pages: int
    noise_k: float
    version_ssim: float
    stamp_threshold: float


def rasters_for(data: bytes, mime: str, s: Settings) -> list[Raster]:
    if mime == "application/pdf":
        return pdf_rasters(data, s.dpi, s.max_pages)
    if mime in IMAGE_TYPES:
        return image_rasters(data, s.max_pages)
    return []


def analyze_document(
    data: bytes,
    mime: str,
    fields: list[FieldBox],
    settings: Settings,
    previous: tuple[bytes, str] | None = None,
    other_stamps: list[dict[str, Any]] | None = None,
) -> ForensicReport:
    if mime != "application/pdf" and mime not in IMAGE_TYPES:
        return ForensicReport(
            [],
            {},
            {"reason": f"forensic analysis applies to PDF and image files, not {mime}"},
            [],
            [
                "Office, CSV and e-mail files are read as structured data; no visual or PDF "
                "structure analysis applies."
            ],
            "not_applicable",
        )
    errors: dict[str, str] = {}
    results: list[AnalysisResult] = []
    rasters: list[Raster] = []
    try:
        rasters = rasters_for(data, mime, settings)
    except Exception as exc:
        errors["render"] = type(exc).__name__

    steps: list[tuple[str, Callable[[], AnalysisResult]]] = []
    if mime == "application/pdf":
        steps.append((pdf_structure.ANALYSIS, lambda: pdf_structure.analyze(data, fields)))
    if rasters:
        steps.append((visual.ANALYSIS, lambda: visual.analyze(rasters, fields, settings.noise_k)))
        steps.append(
            (
                stamps.ANALYSIS,
                lambda: stamps.analyze(rasters, other_stamps or [], settings.stamp_threshold),
            )
        )
        if previous is not None:
            old_data, old_mime = previous
            steps.append(
                (
                    versions.ANALYSIS,
                    lambda: versions.analyze(
                        rasters_for(old_data, old_mime, settings),
                        rasters,
                        fields,
                        settings.version_ssim,
                    ),
                )
            )
    for name, run in steps:
        try:
            results.append(run())
        except Exception as exc:
            logger.warning(
                "forensic_analysis_failed", extra={"analysis": name, "error": type(exc).__name__}
            )
            errors[name] = type(exc).__name__

    structure: dict[str, Any] = {r.analysis_type: r.details for r in results}
    if errors:
        structure["errors"] = errors
    structure["pages_analysed"] = len(rasters)
    limitations: list[str] = []
    for r in results:
        limitations.extend(x for x in r.limitations if x not in limitations)
    metadata = structure.get(pdf_structure.ANALYSIS, {}).get("metadata", {})
    return ForensicReport(
        analysis_types=[r.analysis_type for r in results],
        pdf_metadata=dict(metadata),
        structure=structure,
        anomalies=[a for r in results for a in r.anomalies],
        limitations=limitations,
        status="partial" if errors else "succeeded",
    )
