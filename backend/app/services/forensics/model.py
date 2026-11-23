"""Result types shared by the forensic analyses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models.forensics import MANDATORY_LIMITATION

SEVERITIES = ("info", "low", "medium")  # a single indicator never ranks above medium


@dataclass
class Anomaly:
    type: str
    severity: str
    explanation: str
    page_number: int | None = None
    region: list[float] | None = None  # page units: PDF points, or pixels for image files
    metrics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"severity {self.severity!r} is not allowed for a forensic indicator")

    @property
    def requires_review(self) -> bool:
        return self.severity == "medium"


@dataclass
class AnalysisResult:
    analysis_type: str
    anomalies: list[Anomaly] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FieldBox:
    """An extracted value the forensic checks can relate a region to."""

    field_id: str
    name: str
    value_type: str
    page_number: int
    bbox: tuple[float, float, float, float]


@dataclass
class ForensicReport:
    analysis_types: list[str]
    pdf_metadata: dict[str, Any]
    structure: dict[str, Any]
    anomalies: list[Anomaly]
    limitations: list[str]
    status: str  # succeeded | partial | not_applicable

    def __post_init__(self) -> None:
        # Requirement 3.2: every result states this limitation.
        if MANDATORY_LIMITATION not in self.limitations:
            self.limitations.insert(0, MANDATORY_LIMITATION)


def overlaps(a: list[float] | tuple[float, ...], b: list[float] | tuple[float, ...]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def union(a: list[float] | tuple[float, ...], b: list[float] | tuple[float, ...]) -> list[float]:
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def overlapping_fields(fields: list[FieldBox], page: int, region: list[float]) -> list[FieldBox]:
    return [f for f in fields if f.page_number == page and overlaps(f.bbox, region)]
