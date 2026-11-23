"""Content-based file type detection. The file extension is never trusted."""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass

PDF = "application/pdf"
PNG = "image/png"
JPEG = "image/jpeg"
TIFF = "image/tiff"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV = "text/csv"
EML = "message/rfc822"
ZIP = "application/zip"

SUPPORTED = frozenset({PDF, PNG, JPEG, TIFF, DOCX, XLSX, CSV, EML})
_EML_HEADER = re.compile(r"^(From|To|Subject|Date|Message-ID|MIME-Version|Received):", re.I | re.M)


@dataclass(frozen=True)
class Detection:
    mime: str | None  # None means "unknown"
    reason: str


def _zip_kind(data: bytes) -> Detection:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
    except zipfile.BadZipFile:
        return Detection(None, "zip signature but unreadable archive")
    if "word/document.xml" in names:
        return Detection(DOCX, "OOXML container with word/document.xml")
    if "xl/workbook.xml" in names:
        return Detection(XLSX, "OOXML container with xl/workbook.xml")
    return Detection(ZIP, "zip archive")


def _text_kind(data: bytes) -> Detection:
    sample = data[:65536]
    if b"\x00" in sample:
        return Detection(None, "binary content without a known signature")
    try:
        text = sample.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = sample.decode("latin-1")
        except UnicodeDecodeError:  # pragma: no cover - latin-1 decodes everything
            return Detection(None, "undecodable text")
    head = text.split("\n\n", 1)[0] if "\n\n" in text else text[:4000]
    if len(_EML_HEADER.findall(head)) >= 2:
        return Detection(EML, "RFC 5322 headers")
    lines = [ln for ln in text.splitlines() if ln.strip()][:20]
    if len(lines) >= 2:
        try:
            dialect = csv.Sniffer().sniff("\n".join(lines), delimiters=",;\t|")
            widths = {len(row) for row in csv.reader(lines, dialect)}
            if min(widths) >= 2 and len(widths) <= 3:
                return Detection(CSV, f"delimited text ({dialect.delimiter!r})")
        except csv.Error:
            pass
    return Detection(None, "plain text is not a supported document type")


def detect(data: bytes) -> Detection:
    if data.startswith(b"%PDF-"):
        return Detection(PDF, "%PDF- signature")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return Detection(PNG, "PNG signature")
    if data.startswith(b"\xff\xd8\xff"):
        return Detection(JPEG, "JPEG SOI marker")
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return Detection(TIFF, "TIFF byte-order header")
    if data.startswith(b"PK\x03\x04"):
        return _zip_kind(data)
    if not data:
        return Detection(None, "empty file")
    return _text_kind(data)
