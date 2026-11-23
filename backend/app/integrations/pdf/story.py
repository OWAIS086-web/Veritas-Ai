"""HTML to PDF with PyMuPDF's `Story`, guarded against layouts that never finish.

MuPDF can't split content that is wider than the frame across pages. Such a story keeps
returning "more" while placing the same rows again and then nothing, forever. Two guards:
`soft_break` lets long unbroken tokens (hashes) wrap, and `render_story` fails after a bounded
number of pages, or when a page places nothing, instead of looping.
"""

from __future__ import annotations

import io
import re

import pymupdf

ZWSP = "\u200b"
_LONG = re.compile(r"[0-9A-Za-z]{24,}")
MAX_PAGES = 400


class StoryLayoutError(ValueError):
    """The content could not be laid out on pages."""


def soft_break(text: str, every: int = 16) -> str:
    """Allow line breaks inside runs of 24+ letters and digits (SHA-256 values, long numbers).
    Text with punctuation (filenames, UUIDs, amounts) is left as it is. The visible text is
    unchanged."""
    return _LONG.sub(
        lambda m: ZWSP.join(m[0][i : i + every] for i in range(0, len(m[0]), every)), text
    )


def render_story(
    html: str, css: str, archive: pymupdf.Archive | None = None, margin: float = 36.0
) -> bytes:
    story = pymupdf.Story(html=html, user_css=css, archive=archive)
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    page = pymupdf.paper_rect("a4")
    area = pymupdf.Rect(margin, margin, page.width - margin, page.height - margin)
    more, pages = 1, 0
    try:
        while more:
            pages += 1
            if pages > MAX_PAGES:
                raise StoryLayoutError(f"the layout did not finish within {MAX_PAGES} pages")
            device = writer.begin_page(page)
            more, filled = story.place(area)
            story.draw(device)
            writer.end_page()
            if more and pymupdf.Rect(filled).is_empty:
                raise StoryLayoutError(f"page {pages} could not place any content")
    finally:
        writer.close()
    return buf.getvalue()
