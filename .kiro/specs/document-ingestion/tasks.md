# Tasks: Document Ingestion

- [x] 1. Object storage integration and MinIO service
  - Done when: the storage round trip works, `put_new` refuses to overwrite, and key generation never includes user input.
  - _Requirements: 2.8_
- [x] 2. Cases model, migration 0002, service and API
  - Done when: the CRUD, filter, soft-delete and cross-org 404 tests pass.
  - _Requirements: 1.1–1.4_
- [x] 3. Type detection and archive safety
  - Done when: the detection tests for all 8 types and spoofed extensions pass, plus each ZIP rule and the Hypothesis traversal property.
  - _Requirements: 2.2–2.5, 5.2_
- [x] 4. Upload endpoint with hashing, duplicates, events and audit
  - Done when: the multi-file, duplicate and oversize integration tests and the Hypothesis dedupe property pass.
  - _Requirements: 2.1, 2.6, 2.7, 2.9, 3.1–3.3, 5.1_
- [x] 5. Signed preview access
  - Done when: a valid URL serves the bytes, an expired or tampered one returns 403, and the audit row is written.
  - _Requirements: 4.1–4.2_

## Implementation notes (verified 2026-11-23)
- Object storage is any S3 API through boto3. Docker Compose runs SeaweedFS, because MinIO's community images were discontinued (2025-2026).
- Cursors are opaque base64url tokens, and a malformed cursor returns 422 (it used to be silently ignored, which repeated page 1).
