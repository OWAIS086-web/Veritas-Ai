"""Organization name comparison.

Normalization (casefold, legal suffixes and punctuation removed) is shared with extraction,
so the `key` stored on party fields and the comparison here always agree. Similarity is the
token-sort ratio from rapidfuzz (word order is ignored), scaled to 0..1.
"""

from __future__ import annotations

from rapidfuzz import fuzz

from app.services.extraction.normalize import normalize_name

__all__ = ["name_similarity", "normalize_name"]


def name_similarity(a: str, b: str) -> float:
    """Similarity of two names after normalization, between 0 and 1 (1 means equal)."""
    left, right = normalize_name(a), normalize_name(b)
    if left == right:
        return 1.0
    if not left or not right:
        return 0.0
    return round(fuzz.token_sort_ratio(left, right) / 100.0, 4)
