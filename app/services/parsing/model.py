"""Format-independent page text model with provenance.

Every parser (PDF text layer, OCR, DOCX, XLSX, CSV, EML) produces ParsedPage objects made of
lines. A line keeps its tokens with character offsets, so a regex match on the line text can
be mapped back to the exact tokens, giving a bounding box (positioned formats) or a location
string (sheet!cell, paragraph, header) for every extracted value.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from statistics import mean
from typing import Any

BBox = tuple[float, float, float, float]  # x0, y0, x1, y1; origin top-left
COLUMN_GAP = 14.0  # points: horizontal gap that separates table cells / label and value
CELL_SEP = " | "


@dataclass
class Token:
    text: str
    bbox: BBox | None = None
    location: str | None = None
    confidence: float | None = None
    start: int = 0  # offsets in the line text, set by Line.build
    end: int = 0


@dataclass
class Line:
    text: str
    tokens: list[Token]
    bbox: BBox | None = None
    location: str | None = None

    @staticmethod
    def build(
        tokens: list[Token], location: str | None = None, separators: list[str] | None = None
    ) -> Line:
        parts: list[str] = []
        pos = 0
        for i, tok in enumerate(tokens):
            if i:
                sep = separators[i - 1] if separators else " "
                parts.append(sep)
                pos += len(sep)
            tok.start, tok.end = pos, pos + len(tok.text)
            parts.append(tok.text)
            pos = tok.end
        boxes = [t.bbox for t in tokens if t.bbox is not None]
        bbox = union(boxes) if boxes else None
        return Line(text="".join(parts), tokens=tokens, bbox=bbox, location=location)

    def span(self, start: int, end: int) -> tuple[BBox | None, str | None, float | None]:
        """Box, location and minimum confidence of the tokens covering [start, end)."""
        covered = [t for t in self.tokens if t.start < end and t.end > start]
        if not covered:
            return None, self.location, None
        boxes: list[BBox] = []
        for tok in covered:
            if tok.bbox is None:
                continue
            boxes.append(_slice(tok, max(start, tok.start), min(end, tok.end)))
        locations = [t.location for t in covered if t.location]
        confidences = [t.confidence for t in covered if t.confidence is not None]
        return (
            union(boxes) if boxes else None,
            locations[0] if locations else self.location,
            min(confidences) if confidences else None,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "bbox": _round(self.bbox),
            "location": self.location,
            "tokens": [
                {
                    "s": t.start,
                    "e": t.end,
                    "bbox": _round(t.bbox),
                    "loc": t.location,
                    "conf": None if t.confidence is None else round(t.confidence, 4),
                }
                for t in self.tokens
            ],
        }

    @staticmethod
    def from_json(data: dict[str, Any]) -> Line:
        text = data["text"]
        tokens = [
            Token(
                text=text[t["s"] : t["e"]],
                bbox=_box(t["bbox"]),
                location=t["loc"],
                confidence=t["conf"],
                start=t["s"],
                end=t["e"],
            )
            for t in data["tokens"]
        ]
        return Line(
            text=text, tokens=tokens, bbox=_box(data.get("bbox")), location=data.get("location")
        )


@dataclass
class ParsedPage:
    page_number: int
    width: float | None
    height: float | None
    coord_unit: str  # "pt" | "px"
    method: str  # text_layer | ocr | parser
    lines: list[Line] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def mean_confidence(self) -> float | None:
        values = [t.confidence for ln in self.lines for t in ln.tokens if t.confidence is not None]
        return round(mean(values), 3) if values else None


def _box(value: Any) -> BBox | None:
    if not value:
        return None
    x0, y0, x1, y1 = (float(v) for v in value)
    return (x0, y0, x1, y1)


def union(boxes: list[BBox]) -> BBox:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _slice(tok: Token, start: int, end: int) -> BBox:
    """Horizontal sub-box of a token for a character range (proportional to characters).
    Exact for whole-word matches; an approximation inside multi-word OCR boxes."""
    if tok.bbox is None:
        raise ValueError("token has no box")
    x0, y0, x1, y1 = tok.bbox
    length = max(1, tok.end - tok.start)
    if start <= tok.start and end >= tok.end:
        return tok.bbox
    a = (start - tok.start) / length
    b = (end - tok.start) / length
    return (x0 + (x1 - x0) * a, y0, x0 + (x1 - x0) * b, y1)


def _round(box: BBox | None) -> list[float] | None:
    return None if box is None else [round(v, 2) for v in box]


def assemble_lines(tokens: list[Token], column_gap: float = COLUMN_GAP) -> list[Line]:
    """Group positioned tokens into visual lines (top to bottom, left to right).

    Tokens whose vertical centers are within half a line height join the same line; a wide
    horizontal gap becomes the " | " cell separator.
    """
    boxed = [(t, t.bbox) for t in tokens if t.bbox is not None and t.text.strip()]
    boxed.sort(key=lambda tb: ((tb[1][1] + tb[1][3]) / 2, tb[1][0]))
    rows: list[list[tuple[Token, BBox]]] = []
    centers: list[float] = []
    heights: list[float] = []
    for tok, box in boxed:
        cy = (box[1] + box[3]) / 2
        h = max(1.0, box[3] - box[1])
        if rows and abs(cy - centers[-1]) <= 0.5 * max(h, heights[-1]):
            rows[-1].append((tok, box))
            n = len(rows[-1])
            centers[-1] = centers[-1] + (cy - centers[-1]) / n
            heights[-1] = max(heights[-1], h)
        else:
            rows.append([(tok, box)])
            centers.append(cy)
            heights.append(h)
    lines: list[Line] = []
    for row in rows:
        row.sort(key=lambda tb: tb[1][0])
        seps = [
            CELL_SEP if cur[1][0] - prev[1][2] > column_gap else " "
            for prev, cur in itertools.pairwise(row)
        ]
        lines.append(Line.build([t for t, _ in row], separators=seps))
    return lines


_EN_STOPWORDS = frozenset(
    "the of and to in for on at by with from is are be this that as or no date total "
    "invoice order payment shipment".split()
)


def detect_language(text: str) -> str | None:
    """Very small heuristic: 'en' when English function words are common, else unknown."""
    words = [w.strip(".,:;()").lower() for w in text.split()]
    words = [w for w in words if w.isalpha()]
    if len(words) < 10:
        return None
    ratio = sum(w in _EN_STOPWORDS for w in words) / len(words)
    return "en" if ratio >= 0.05 else None
