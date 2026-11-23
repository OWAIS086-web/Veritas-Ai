"""Anti-fabrication check: a value is kept only if it appears on the page it cites."""

from __future__ import annotations

import re

_DASHES = re.compile(r"[\u2010-\u2015\u2212]")
_SPACE = re.compile(r"\s+")
_DIGIT_GROUPING = re.compile(r"(?<=\d)[,\s](?=\d{3}\b)")


def normalize_text(text: str) -> str:
    text = _DASHES.sub("-", text.casefold()).replace("|", " ")
    return _SPACE.sub(" ", text).strip()


def _without_grouping(text: str) -> str:
    return _DIGIT_GROUPING.sub("", text)


def value_is_supported(value: str, page_text: str) -> bool:
    """True if `value` occurs in `page_text` after case, whitespace, dash and
    thousands-separator normalization."""
    v = normalize_text(value)
    if not v:
        return False
    page = normalize_text(page_text)
    if v in page:
        return True
    return _without_grouping(v) in _without_grouping(page)
