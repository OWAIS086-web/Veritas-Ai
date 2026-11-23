# Req: document-ingestion 2.2-2.5, 5.2
from __future__ import annotations

import io
import zipfile

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.services.ingestion import detect as d
from app.services.ingestion.archive import (
    ArchiveLimits,
    ArchiveRejectedError,
    expand,
    is_unsafe_name,
)

LIMITS = ArchiveLimits(
    max_entries=5, max_total_bytes=1_000_000, max_ratio=100, max_entry_bytes=500_000
)
PDF_BYTES = b"%PDF-1.7\n1 0 obj<<>>endobj\n%%EOF\n"


def _zip(files: dict[str, bytes], compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _ooxml(marker: str) -> bytes:
    return _zip({"[Content_Types].xml": b"<Types/>", marker: b"<x/>"})


@pytest.mark.parametrize(
    ("data", "mime"),
    [
        (PDF_BYTES, d.PDF),
        (b"\x89PNG\r\n\x1a\n" + b"\0" * 20, d.PNG),
        (b"\xff\xd8\xff\xe0" + b"\0" * 20, d.JPEG),
        (b"II*\x00" + b"\0" * 20, d.TIFF),
        (b"MM\x00*" + b"\0" * 20, d.TIFF),
        (_ooxml("word/document.xml"), d.DOCX),
        (_ooxml("xl/workbook.xml"), d.XLSX),
        (b"field,value\ninvoice_number,INV-1\ntotal,48000\n", d.CSV),
        (b"From: a@example.com\nTo: b@example.com\nSubject: Invoice\n\nBody text\n", d.EML),
        (_zip({"a.pdf": PDF_BYTES}), d.ZIP),
    ],
)
def test_detects_supported_types_from_content(data: bytes, mime: str) -> None:
    assert d.detect(data).mime == mime


@pytest.mark.parametrize(
    "data",
    [b"", b"MZ\x90\x00\x03" + b"\x00" * 50, b"just a sentence of plain prose\n", b"\x7fELF\x02"],
)
def test_rejects_unknown_content(data: bytes) -> None:
    assert d.detect(data).mime is None


def test_extension_is_irrelevant() -> None:
    # An executable renamed to .pdf is still unknown; a PDF named .txt is still a PDF.
    assert d.detect(b"MZ" + b"\x00" * 100).mime is None
    assert d.detect(PDF_BYTES).mime == d.PDF


def test_expand_returns_entries_by_basename() -> None:
    entries = expand(_zip({"docs/invoice.pdf": PDF_BYTES, "po.pdf": PDF_BYTES}), LIMITS)
    assert sorted(e.name for e in entries) == ["invoice.pdf", "po.pdf"]
    assert all(e.data == PDF_BYTES for e in entries)


@pytest.mark.parametrize(
    ("files", "reason"),
    [
        ({"../evil.pdf": PDF_BYTES}, "unsafe_entry_path"),
        ({"/etc/passwd": PDF_BYTES}, "unsafe_entry_path"),
        ({"C:/Windows/x.pdf": PDF_BYTES}, "unsafe_entry_path"),
        ({"a/../../x.pdf": PDF_BYTES}, "unsafe_entry_path"),
        ({f"f{i}.pdf": PDF_BYTES for i in range(6)}, "too_many_entries:6"),
        ({"bomb.csv": b"0" * 400_000}, "compression_ratio_exceeded"),
        ({"inner.zip": _zip({"a.pdf": PDF_BYTES})}, "nested_archive"),
    ],
)
def test_expand_rejects_unsafe_archives(files: dict[str, bytes], reason: str) -> None:
    with pytest.raises(ArchiveRejectedError) as info:
        expand(_zip(files), LIMITS)
    assert info.value.reason == reason


def test_expand_rejects_oversized_and_invalid() -> None:
    big = {"big.pdf": PDF_BYTES + bytes(range(256)) * 3000}  # ~768 KB, low ratio
    with pytest.raises(ArchiveRejectedError, match="entry_too_large"):
        expand(_zip(big, zipfile.ZIP_STORED), LIMITS)
    with pytest.raises(ArchiveRejectedError, match="invalid_archive"):
        expand(b"PK\x03\x04garbage", LIMITS)


segment = st.text(alphabet=st.characters(blacklist_characters="/\\\x00"), min_size=1, max_size=8)


@given(st.lists(segment, min_size=0, max_size=3), st.lists(segment, min_size=0, max_size=3))
def test_any_name_with_a_parent_segment_is_unsafe(before: list[str], after: list[str]) -> None:
    assert is_unsafe_name("/".join([*before, "..", *after]))
    assert is_unsafe_name("\\".join([*before, "..", *after]))


@given(st.lists(segment.filter(lambda s: s not in {".."} and ":" not in s), min_size=1, max_size=4))
def test_relative_names_without_parent_segments_are_safe(parts: list[str]) -> None:
    assert not is_unsafe_name("/".join(parts))
