"""Upload: validate, expand ZIPs, hash, detect duplicates, store originals, create rows.

Originals are written once with put_new (never overwritten) under a server-generated,
organization-prefixed key. The user's filename is metadata only.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.integrations.storage.base import ObjectStore, original_key
from app.models import Document, DocumentStatus, DocumentVersion
from app.schemas.documents import UploadResult
from app.services.audit import service as audit
from app.services.cases.service import get_case
from app.services.identity.principal import Principal, RequestMeta
from app.services.ingestion.archive import ArchiveLimits, ArchiveRejectedError, expand
from app.services.ingestion.detect import SUPPORTED, ZIP, detect

MAX_FILENAME = 255


@dataclass(frozen=True)
class IncomingFile:
    filename: str
    data: bytes
    too_large: bool = False


def safe_display_name(name: str | None) -> str:
    """Last path segment, control characters removed, truncated. Display metadata only."""
    base = (name or "unnamed").replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(ch for ch in base if ch.isprintable() and ch not in '<>:"|?*').strip()
    return (cleaned or "unnamed")[:MAX_FILENAME]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _limits() -> ArchiveLimits:
    s = get_settings()
    return ArchiveLimits(
        max_entries=s.zip_max_entries,
        max_total_bytes=s.zip_max_total_mb * 1024 * 1024,
        max_ratio=s.zip_max_ratio,
        max_entry_bytes=s.max_upload_mb * 1024 * 1024,
    )


async def _accept(
    session: AsyncSession,
    store: ObjectStore,
    principal: Principal,
    case_id: uuid.UUID,
    name: str,
    data: bytes,
    mime: str,
    reason: str,
    archive: str | None,
    seen: dict[str, uuid.UUID],
    meta: RequestMeta,
) -> UploadResult:
    org = principal.organization_id
    digest = sha256(data)
    if digest in seen:
        return UploadResult(
            filename=name,
            status="duplicate",
            document_id=seen[digest],
            reason="same content earlier in this upload",
            detected_type=mime,
        )
    existing = await session.scalar(
        select(Document.id).where(
            Document.organization_id == org, Document.case_id == case_id, Document.sha256 == digest
        )
    )
    if existing is not None:
        return UploadResult(
            filename=name,
            status="duplicate",
            document_id=existing,
            reason="identical content already in this case",
            detected_type=mime,
        )
    previous = await session.scalar(
        select(Document)
        .where(
            Document.organization_id == org,
            Document.case_id == case_id,
            Document.original_filename == name,
        )
        .order_by(Document.uploaded_at.desc())
        .limit(1)
    )
    doc_id = uuid.uuid4()
    key = original_key(org, doc_id)
    try:
        async with session.begin_nested():  # savepoint: a concurrent duplicate is not a 500
            session.add(
                Document(
                    id=doc_id,
                    organization_id=org,
                    case_id=case_id,
                    original_filename=name,
                    sha256=digest,
                    storage_key=key,
                    mime_type=mime,
                    detection_reason=reason[:120],
                    size_bytes=len(data),
                    status=DocumentStatus.UPLOADED,
                    pipeline_version=get_settings().pipeline_version,
                    source_archive=archive,
                    uploaded_by=principal.user_id,
                )
            )
            await session.flush()
    except IntegrityError:
        winner = await session.scalar(
            select(Document.id).where(
                Document.organization_id == org,
                Document.case_id == case_id,
                Document.sha256 == digest,
            )
        )
        return UploadResult(
            filename=name,
            status="duplicate",
            document_id=winner,
            reason="identical content uploaded concurrently",
            detected_type=mime,
        )
    if previous is not None:
        # Same name, different bytes: a new version. Both originals are kept unchanged.
        session.add(
            DocumentVersion(
                organization_id=org, document_id=doc_id, supersedes_id=previous.id, sha256=digest
            )
        )
    await store.put_new(key, data, mime)  # if storage fails the transaction rolls back
    seen[digest] = doc_id
    await audit.record(
        session,
        "document.upload",
        organization_id=org,
        actor_user_id=principal.user_id,
        resource_type="document",
        resource_id=doc_id,
        meta=meta,
        metadata={
            "sha256": digest,
            "mime": mime,
            "size": len(data),
            "case_id": str(case_id),
            "archive": archive,
        },
    )
    return UploadResult(filename=name, status="accepted", document_id=doc_id, detected_type=mime)


async def upload(
    session: AsyncSession,
    store: ObjectStore,
    principal: Principal,
    case_id: uuid.UUID,
    files: list[IncomingFile],
    meta: RequestMeta,
) -> list[UploadResult]:
    await get_case(session, principal.organization_id, case_id)  # 404 across tenants
    results: list[UploadResult] = []
    seen: dict[str, uuid.UUID] = {}
    for incoming in files:
        name = safe_display_name(incoming.filename)
        if incoming.too_large:
            results.append(UploadResult(filename=name, status="rejected", reason="too_large"))
            continue
        detection = detect(incoming.data)
        if detection.mime == ZIP:
            try:
                entries = expand(incoming.data, _limits())
            except ArchiveRejectedError as exc:
                results.append(
                    UploadResult(
                        filename=name, status="rejected", reason=exc.reason, detected_type=ZIP
                    )
                )
                continue
            for entry in entries:
                entry_name = safe_display_name(entry.name)
                inner = detect(entry.data)
                if inner.mime not in SUPPORTED:
                    results.append(
                        UploadResult(
                            filename=entry_name,
                            status="rejected",
                            reason=f"unsupported_type:{inner.reason}",
                            detected_type=inner.mime,
                        )
                    )
                    continue
                results.append(
                    await _accept(
                        session,
                        store,
                        principal,
                        case_id,
                        entry_name,
                        entry.data,
                        inner.mime,
                        inner.reason,
                        name,
                        seen,
                        meta,
                    )
                )
            continue
        if detection.mime not in SUPPORTED:
            results.append(
                UploadResult(
                    filename=name,
                    status="rejected",
                    reason=f"unsupported_type:{detection.reason}",
                    detected_type=detection.mime,
                )
            )
            continue
        results.append(
            await _accept(
                session,
                store,
                principal,
                case_id,
                name,
                incoming.data,
                detection.mime,
                detection.reason,
                None,
                seen,
                meta,
            )
        )
    return results
