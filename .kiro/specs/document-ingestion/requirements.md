# Requirements: Document Ingestion

## Introduction
Investigation cases, safe upload of documents and archives, validation, hashing, duplicate detection, immutable original storage, and processing status.

## Requirement 1: Cases
1. WHEN a user with `cases:write` calls `POST /cases` with `{title, objective, investigation_type, priority}` THE SYSTEM SHALL create a case in the caller's organization with status `open`.
2. WHEN `GET /cases` is called THE SYSTEM SHALL return non-deleted cases of the caller's organization with document and finding counts, filterable by `status`, `priority` and `q` (title search), with cursor pagination.
3. WHEN `DELETE /cases/{id}` is called by a role with `cases:delete` THE SYSTEM SHALL set `deleted_at`, and the case and its documents SHALL disappear from every API.
4. WHEN any case endpoint targets another organization's case THE SYSTEM SHALL return 404.

## Requirement 2: Upload
1. WHEN `POST /cases/{case_id}/documents` receives one or more multipart files THE SYSTEM SHALL validate each file independently and return 201 with a per-file result `{filename, status: accepted|duplicate|rejected, document_id?, reason?}`.
2. THE SYSTEM SHALL accept PDF, PNG, JPEG, TIFF, DOCX, XLSX, CSV and EML, determined from the file's content (magic bytes or structure), not from its extension.
3. WHEN a file exceeds `VERITAS_MAX_UPLOAD_MB` THE SYSTEM SHALL reject it with reason `too_large`.
4. WHEN a file's detected type is not supported THE SYSTEM SHALL reject it with reason `unsupported_type:<detected>`.
5. WHEN a ZIP is uploaded THE SYSTEM SHALL extract supported entries only if: entries ≤ `VERITAS_ZIP_MAX_ENTRIES`, total uncompressed size ≤ `VERITAS_ZIP_MAX_TOTAL_MB`, every entry's compression ratio ≤ `VERITAS_ZIP_MAX_RATIO`, no nested ZIPs, and no entry name is absolute or contains `..` or a drive letter. Otherwise THE SYSTEM SHALL reject the whole archive with the reason.
6. THE SYSTEM SHALL compute SHA-256 over the original bytes.
7. WHEN `(organization_id, case_id, sha256)` already exists THE SYSTEM SHALL return `duplicate` with the existing `document_id` and SHALL NOT store a second copy.
8. THE SYSTEM SHALL store the original at `{organization_id}/{document_id}/original` and SHALL NEVER modify or overwrite it.
9. THE SYSTEM SHALL write `document.uploaded` and `document.validated` events and an audit entry per accepted file.

## Requirement 3: Document metadata and listing
1. Each document SHALL record id, organization_id, case_id, original_filename, sha256, storage_key, mime_type, size_bytes, page_count (null until parsed), doc_type (null until classified), classification_confidence, status, uploaded_by and uploaded_at.
2. WHEN `GET /cases/{case_id}/documents` is called THE SYSTEM SHALL list them with status and stage progress.
3. WHEN `GET /documents/{id}` targets another organization THE SYSTEM SHALL return 404.

## Requirement 4: Preview
1. WHEN `GET /documents/{id}/preview` is called by a role with `documents:read` THE SYSTEM SHALL return a signed URL valid for 60 s and write a `document.access` audit entry.
2. WHEN a signed URL is expired or tampered with THE SYSTEM SHALL refuse it (403).

## Requirement 5: Property guarantees
1. FOR ANY byte string, hashing SHALL be deterministic, and two uploads of identical bytes to the same case SHALL yield exactly one stored document.
2. FOR ANY ZIP entry name containing traversal segments, THE SYSTEM SHALL reject the archive.
