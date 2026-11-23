# Design: Document Ingestion

## Components
| Component | File | Responsibility |
|---|---|---|
| Cases service | `app/services/cases/service.py` | CRUD, soft delete, counts |
| Type detection | `app/services/ingestion/detect.py` | Magic bytes: `%PDF-`, PNG signature, `\xFF\xD8\xFF`, `II*\0`/`MM\0*`. A ZIP container with `word/document.xml` is DOCX, with `xl/workbook.xml` is XLSX, anything else is a ZIP archive. CSV and EML use a text sniff: UTF-8 decodable, then RFC 5322 headers (`From:`, `Subject:`, `Date:`) for EML, otherwise `csv.Sniffer` for CSV. |
| Archive expansion | `app/services/ingestion/archive.py` | Safe ZIP expansion following Req 2.5 |
| Ingestion service | `app/services/ingestion/service.py` | Validate, hash, dedupe, store, insert the row, emit events, enqueue processing |
| Storage | `app/integrations/storage/{base,s3_store}.py` | `ObjectStore` protocol: `put_new` (originals only, refuses an existing key), `put_derived` (never an original key), `get`, `exists`. boto3 against any S3 API; SeaweedFS in Compose, because MinIO's community images were discontinued. |
| Signed access | `app/core/signing.py` | HMAC-SHA256 over `document_id|exp|org`, served by `GET /files/{token}` |

## Data model (migration 0002)
- `cases(id, organization_id, title, objective, investigation_type, priority, status, created_by, created_at, updated_at, deleted_at)`, with RLS
- `documents(id, organization_id, case_id, original_filename, sha256 char(64), storage_key, mime_type, size_bytes, page_count, doc_type, classification_confidence numeric(4,3), language, status, error, pipeline_version, uploaded_by, uploaded_at, unique(organization_id, case_id, sha256))`, with RLS
- `document_versions(id, organization_id, document_id, sha256, storage_key, supersedes_id, created_at)`, with RLS
- `document_stages(id, organization_id, document_id, stage, pipeline_version, status, attempts, started_at, finished_at, error, metrics jsonb, unique(document_id, stage, pipeline_version))`, with RLS

## Upload flow
1. Stream each part to a temp file with a running size check (abort past the limit).
2. Detect the type, then expand the archive if it is one (each entry re-enters at step 2 at depth 1).
3. SHA-256, then a duplicate lookup under RLS.
4. Insert the document row (`uploaded`), then `put_new` the original. If storage fails, the transaction rolls back.
5. Commit, then enqueue `process_document(document_id)` (see document-intelligence).

## Failure handling
| Failure | Behavior |
|---|---|
| Storage write fails | Roll back the row and return `rejected` with reason `storage_error` |
| Duplicate race (unique violation) | Return `duplicate` with the existing id |
| Malformed ZIP | Reject with `invalid_archive` |
| Enqueue fails after commit | The document stays `uploaded`. `POST /cases/{id}/process` re-enqueues pending documents. |

## Testing
- Unit: detection for every supported type plus spoofed extensions; each archive rule; key generation ignores the filename.
- Property: hash determinism; traversal names always rejected.
- Integration: multi-file upload, duplicate, oversize, cross-org 404, preview signing and expiry.
