"""Text comparison on the registered pages, from each document's own text layer or OCR lines
(the `document_pages` rows written by the processing pipeline).

Original tokens are mapped onto the test page through the registration. Each test line is
compared with the original text found at the same place. Both sides are compared as their
tokens joined by single spaces, so layout separators in the stored line text never count as a
change. A change is widened to whole words and located with each document's own token boxes.
Original text with no counterpart is reported as removed, test text with none as added.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field

from app.services.doccompare.geometry import Box, center, clip, contains_point, expand, union, valid
from app.services.doccompare.pages import PagePair
from app.services.parsing.model import Line, Token

_SPACE = re.compile(r"\s+")
_DIGITS = re.compile(r"\d+")
OCR_SIMILARITY = 0.85  # below this, OCR'd letter text counts as changed (above it is OCR noise)
MIN_LINE_OVERLAP = 0.5  # vertical overlap (share of the smaller height) to belong to a line


@dataclass(frozen=True)
class TextChange:
    kind: str  # text_changed | text_added | text_removed
    test_page: int
    region: Box  # test page units (validated)
    original_region: Box | None  # original page units (validated)
    original_text: str | None  # the changed words of the original
    test_text: str | None  # the changed words of the test document
    line_text: str  # the whole test line (context)
    original_line: str  # the whole original text at that place (context)
    method: str  # text_layer | ocr
    confidence: float | None  # minimum OCR confidence of the tokens involved, None if unmeasured
    digits_changed: bool


@dataclass
class _Tok:
    """A token with its line (for character-accurate boxes) and its box on the test page."""

    text: str
    line: Line
    token: Token
    box: Box  # on the test page (original tokens: mapped through the registration)
    page_box: Box  # on its own page
    used: bool = field(default=False)


def normalize(text: str) -> str:
    return _SPACE.sub(" ", unicodedata.normalize("NFKC", text)).strip().casefold()


def digits(text: str) -> list[str]:
    return _DIGITS.findall(text.replace(",", "").replace(" ", ""))


def differs(original: str, test: str, method: str) -> bool:
    """Digits must match exactly. Other text must match exactly from a text layer, and closely
    (similarity >= OCR_SIMILARITY, after normalization) from OCR."""
    a, b = normalize(original), normalize(test)
    if a == b:
        return False
    if digits(a) != digits(b):
        return True
    if method == "text_layer":
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() < OCR_SIMILARITY


def _tokens(line: Line) -> list[tuple[str, Token]]:
    return [
        (line.text[t.start : t.end], t)
        for t in line.tokens
        if t.bbox is not None and valid(list(t.bbox)) and line.text[t.start : t.end].strip()
    ]


def _join(toks: list[_Tok]) -> tuple[str, list[tuple[int, int]]]:
    parts, spans, pos = [], [], 0
    for t in toks:
        spans.append((pos, pos + len(t.text)))
        parts.append(t.text)
        pos += len(t.text) + 1
    return " ".join(parts), spans


def _words(text: str, a: int, b: int) -> tuple[int, int]:
    """Widen [a, b) inside one token's text to whole words."""
    while a > 0 and not text[a - 1].isspace():
        a -= 1
    while b < len(text) and not text[b].isspace():
        b += 1
    return a, b


def _locate(
    toks: list[_Tok], spans: list[tuple[int, int]], lo: int, hi: int, on_test: bool
) -> tuple[list[Box], list[str]]:
    """Boxes and words of the tokens covering joined range [lo, hi). An empty range (pure
    insertion on the other side) takes the word just before it."""
    if hi <= lo:
        lo, hi = max(0, lo - 1), max(1, lo)
    boxes: list[Box] = []
    words: list[str] = []
    for t, (s, e) in zip(toks, spans, strict=True):
        if s >= hi or e <= lo:
            continue
        a, b = _words(t.text, max(0, lo - s), min(len(t.text), hi - s))
        if a >= b:
            continue
        words.append(t.text[a:b])
        if a == 0 and b == len(t.text):
            boxes.append(t.box if on_test else t.page_box)
            continue
        span, _, _ = t.line.span(t.token.start + a, t.token.start + b)
        # The line's own boxes are in its document's page units: the test page for test
        # tokens, the original page for original tokens.
        if span is None or not valid(list(span)):
            boxes.append(t.box if on_test else t.page_box)
        else:
            boxes.append(list(span))
    return boxes, words


def _group(tokens: list[_Tok]) -> list[list[_Tok]]:
    """Group leftover original tokens into lines (same row, close horizontally)."""
    groups: list[list[_Tok]] = []
    for tok in sorted(tokens, key=lambda t: (center(t.box)[1], t.box[0])):
        h = tok.box[3] - tok.box[1]
        for g in groups:
            last = g[-1]
            same_row = abs(center(last.box)[1] - center(tok.box)[1]) < max(h, 1) * 0.6
            if same_row and tok.box[0] - last.box[2] < max(h, 1) * 3:
                g.append(tok)
                break
        else:
            groups.append([tok])
    return groups


def _assign(orig: list[_Tok], line_boxes: list[Box]) -> dict[int, list[_Tok]]:
    """Give each mapped original token to the test line it overlaps most vertically (at least
    half of the smaller height, and horizontally within the line). A token no line takes is
    later reported as removed. Assigning globally keeps one line from taking its
    neighbour's text when lines are close together or the scan is slightly skewed."""
    out: dict[int, list[_Tok]] = {}
    for t in orig:
        cx, _ = center(t.box)
        th = t.box[3] - t.box[1]
        best, best_ratio = -1, MIN_LINE_OVERLAP
        for i, lb in enumerate(line_boxes):
            lh = lb[3] - lb[1]
            if not contains_point(expand(lb, lh * 0.5, 0), (cx, (lb[1] + lb[3]) / 2)):
                continue
            ov = min(t.box[3], lb[3]) - max(t.box[1], lb[1])
            ratio = ov / max(min(th, lh), 1e-6)
            if ratio > best_ratio:
                best, best_ratio = i, ratio
        if best >= 0:
            out.setdefault(best, []).append(t)
    return out


def _min_conf(toks: list[_Tok]) -> float | None:
    confs = [t.token.confidence for t in toks if t.token.confidence is not None]
    return min(confs) if confs else None


def compare_page(
    pair: PagePair,
    original_lines: list[Line],
    test_lines: list[Line],
    original_method: str,
    test_method: str,
) -> list[TextChange]:
    method = "text_layer" if original_method == test_method == "text_layer" else "ocr"
    tw, th = pair.test_frame.page_width, pair.test_frame.page_height
    ow, oh = pair.original_frame.page_width, pair.original_frame.page_height
    orig: list[_Tok] = []
    for ln in original_lines:
        for text, tok in _tokens(ln):
            page_box = list(tok.bbox or ())
            mapped = clip(pair.original_box_to_test(page_box), tw, th)
            if mapped is not None:
                orig.append(_Tok(text, ln, tok, mapped, page_box))
    usable = [
        ln for ln in test_lines if ln.bbox is not None and valid(list(ln.bbox)) and _tokens(ln)
    ]
    assigned = _assign(orig, [list(ln.bbox or ()) for ln in usable])
    changes: list[TextChange] = []
    for index, ln in enumerate(usable):
        test_toks = [
            _Tok(t, ln, tok, list(tok.bbox or ()), list(tok.bbox or ())) for t, tok in _tokens(ln)
        ]
        lb = list(ln.bbox or ())
        here = sorted(assigned.get(index, []), key=lambda t: t.box[0])
        for t in here:
            t.used = True
        test_text, test_spans = _join(test_toks)
        confidence = _min_conf(here + test_toks)
        if not here:
            region = clip(union([t.box for t in test_toks]), tw, th)
            if region is not None:
                changes.append(
                    TextChange(
                        "text_added",
                        pair.test_page,
                        region,
                        None,
                        None,
                        test_text,
                        test_text,
                        "",
                        method,
                        confidence,
                        bool(digits(test_text)),
                    )
                )
            continue
        original_text, orig_spans = _join(here)
        if not differs(original_text, test_text, method):
            continue
        t_boxes: list[Box] = []
        o_boxes: list[Box] = []
        t_words: list[str] = []
        o_words: list[str] = []
        matcher = difflib.SequenceMatcher(None, original_text, test_text, autojunk=False)
        for op, i1, i2, j1, j2 in matcher.get_opcodes():
            if op == "equal":
                continue
            boxes, words = _locate(test_toks, test_spans, j1, j2, on_test=True)
            t_boxes += boxes
            t_words += [w for w in words if w not in t_words]
            boxes, words = _locate(here, orig_spans, i1, i2, on_test=False)
            o_boxes += boxes
            o_words += [w for w in words if w not in o_words]
        region = clip(union(t_boxes) if t_boxes else lb, tw, th)
        if region is None:
            continue
        original_region = clip(union(o_boxes or [t.page_box for t in here]), ow, oh)
        changes.append(
            TextChange(
                "text_changed",
                pair.test_page,
                region,
                original_region,
                " ".join(o_words) or original_text,
                " ".join(t_words) or test_text,
                test_text,
                original_text,
                method,
                confidence,
                digits(original_text) != digits(test_text),
            )
        )
    for group in _group([t for t in orig if not t.used]):
        group.sort(key=lambda t: t.box[0])
        text = " ".join(t.text for t in group)
        region = clip(union([t.box for t in group]), tw, th)
        if region is None or not normalize(text):
            continue
        original_region = clip(union([t.page_box for t in group]), ow, oh)
        changes.append(
            TextChange(
                "text_removed",
                pair.test_page,
                region,
                original_region,
                text,
                None,
                "",
                text,
                method,
                _min_conf(group),
                bool(digits(text)),
            )
        )
    return changes
