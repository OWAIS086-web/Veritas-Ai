"""Direct parsers for DOCX, XLSX, CSV and EML. Values carry a location instead of a box."""

from __future__ import annotations

import csv
import email
import io
from email import policy
from email.message import EmailMessage

from docx import Document as DocxDocument
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from app.services.parsing.model import CELL_SEP, Line, ParsedPage, Token


def _page(lines: list[Line]) -> ParsedPage:
    return ParsedPage(
        page_number=1, width=None, height=None, coord_unit="pt", method="parser", lines=lines
    )


def _row_line(cells: list[tuple[str, str]], location: str) -> Line | None:
    tokens = [Token(text=text, location=loc, confidence=1.0) for text, loc in cells if text]
    if not tokens:
        return None
    return Line.build(tokens, location=location, separators=[CELL_SEP] * (len(tokens) - 1))


def parse_docx(data: bytes) -> list[ParsedPage]:
    doc = DocxDocument(io.BytesIO(data))
    lines: list[Line] = []
    for p_index, para in enumerate(doc.paragraphs, start=1):
        text = para.text.strip()
        if text:
            loc = f"paragraph {p_index}"
            lines.append(Line.build([Token(text=text, location=loc, confidence=1.0)], location=loc))
    for t_index, table in enumerate(doc.tables, start=1):
        for r_index, row in enumerate(table.rows, start=1):
            cells = [
                (c.text.strip(), f"table {t_index} row {r_index} col {c_i}")
                for c_i, c in enumerate(row.cells, start=1)
            ]
            line = _row_line(cells, f"table {t_index} row {r_index}")
            if line:
                lines.append(line)
    return [_page(lines)]


def parse_xlsx(data: bytes) -> list[ParsedPage]:
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    pages: list[ParsedPage] = []
    try:
        for s_index, ws in enumerate(wb.worksheets, start=1):
            lines: list[Line] = []
            for r_index, row in enumerate(ws.iter_rows(values_only=True), start=1):
                cells = [
                    (
                        "" if value is None else str(value).strip(),
                        f"{ws.title}!{get_column_letter(c_index)}{r_index}",
                    )
                    for c_index, value in enumerate(row, start=1)
                ]
                line = _row_line(cells, f"{ws.title}!row {r_index}")
                if line:
                    lines.append(line)
            page = _page(lines)
            page.page_number = s_index
            pages.append(page)
    finally:
        wb.close()
    return pages


def parse_csv(data: bytes) -> list[ParsedPage]:
    text = data.decode("utf-8-sig", errors="replace")
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(
            text[:4096], delimiters=",;\t|"
        )
    except csv.Error:
        dialect = csv.excel
    lines: list[Line] = []
    for r_index, row in enumerate(csv.reader(io.StringIO(text), dialect), start=1):
        cells = [
            (cell.strip(), f"row {r_index} col {c_index}")
            for c_index, cell in enumerate(row, start=1)
        ]
        line = _row_line(cells, f"row {r_index}")
        if line:
            lines.append(line)
    return [_page(lines)]


def parse_eml(data: bytes) -> tuple[list[ParsedPage], list[str]]:
    """Headers and the plain-text body. Attachments are listed, never executed or parsed."""
    msg = email.message_from_bytes(data, policy=policy.default)
    if not isinstance(msg, EmailMessage):
        raise ValueError("not an RFC 5322 message")
    lines: list[Line] = []
    for header in ("From", "To", "Date", "Subject"):
        value = msg.get(header)
        if value:
            loc = f"header {header}"
            lines.append(
                Line.build(
                    [Token(text=f"{header}: {value}", location=loc, confidence=1.0)], location=loc
                )
            )
    body = msg.get_body(preferencelist=("plain",))
    content = body.get_content() if body is not None else ""
    for l_index, raw in enumerate(str(content).splitlines(), start=1):
        text = raw.strip()
        if text:
            loc = f"body line {l_index}"
            lines.append(Line.build([Token(text=text, location=loc, confidence=1.0)], location=loc))
    attachments = [part.get_filename() or "unnamed" for part in msg.iter_attachments()]
    return [_page(lines)], attachments
