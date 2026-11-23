"""Safe ZIP expansion: entry, size, ratio, nesting and path checks before reading anything."""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.services.ingestion.detect import ZIP, detect

_DRIVE = re.compile(r"^[A-Za-z]:")


class ArchiveRejectedError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ArchiveLimits:
    max_entries: int
    max_total_bytes: int
    max_ratio: int
    max_entry_bytes: int


@dataclass(frozen=True)
class ArchiveEntry:
    name: str  # display name (last path segment), metadata only
    data: bytes


def is_unsafe_name(name: str) -> bool:
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or _DRIVE.match(normalized):
        return True
    return any(part == ".." for part in PurePosixPath(normalized).parts)


def expand(data: bytes, limits: ArchiveLimits) -> list[ArchiveEntry]:
    """Return the files in a ZIP. The whole archive is rejected if any rule is violated."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ArchiveRejectedError("invalid_archive") from exc
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > limits.max_entries:
            raise ArchiveRejectedError(f"too_many_entries:{len(infos)}")
        total = 0
        for info in infos:
            if is_unsafe_name(info.filename):
                raise ArchiveRejectedError("unsafe_entry_path")
            if info.flag_bits & 0x1:
                raise ArchiveRejectedError("encrypted_entry")
            total += info.file_size
            if info.file_size > limits.max_entry_bytes:
                raise ArchiveRejectedError("entry_too_large")
            if total > limits.max_total_bytes:
                raise ArchiveRejectedError("archive_too_large")
            if info.file_size > 0 and info.compress_size == 0:
                raise ArchiveRejectedError("compression_ratio_exceeded")
            if info.compress_size and info.file_size / info.compress_size > limits.max_ratio:
                raise ArchiveRejectedError("compression_ratio_exceeded")
        entries: list[ArchiveEntry] = []
        for info in infos:
            # Read at most the declared size + 1 so a lying header can't inflate memory.
            with zf.open(info) as fh:
                content = fh.read(info.file_size + 1)
            if len(content) != info.file_size:
                raise ArchiveRejectedError("entry_size_mismatch")
            if detect(content).mime == ZIP:
                raise ArchiveRejectedError("nested_archive")
            name = PurePosixPath(info.filename.replace("\\", "/")).name or "unnamed"
            entries.append(ArchiveEntry(name=name, data=content))
        return entries
