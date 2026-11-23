# Tasks: Multimodal Document Intelligence

- [x] 1. Synthetic sample generator (7 shipment PDFs plus format variants, labelled SYNTHETIC DEMONSTRATION DATA)
  - Done when: the output is deterministic (same hashes on re-run) and every file opens with its library.
- [x] 2. Migration 0003, page and extraction models
  - Done when: the migration cycle passes and RLS isolation holds for the new tables.
  - _Requirements: 3.5, 4.2_
- [x] 3. Parsers: PDF text layer, DOCX, XLSX, CSV, EML
  - Done when: the ground-truth strings are found in each sample and the boxes fall within the page bounds.
  - _Requirements: 3.1, 3.4, 3.5_
- [x] 4. OCR path (OpenCV and PaddleOCR) and Docling layout
  - Done when: the scanned variant yields OCR text containing the invoice number, with confidence from PaddleOCR.
  - _Requirements: 3.2, 3.3_
- [x] 5. Classification
  - Done when: all 7 samples classify correctly and an unrelated text classifies as `unknown`.
  - _Requirements: 2.1, 2.2_
- [x] 6. Normalizers and the anti-fabrication check
  - Done when: the Hypothesis properties for amounts, dates and verification pass.
  - _Requirements: 4.3, 4.4, 4.7_
- [x] 7. Rules extractor and provider extractor (OpenAI-compatible plus replay)
  - Done when: the rules extractor yields the correct totals on all 7 documents, the replay tests pass, and an injected unsupported value is rejected.
  - _Requirements: 4.1, 4.2, 4.5, 4.6_
- [x] 8. Celery pipeline, retries, idempotency, retry and process endpoints
  - Done when: a re-run creates no duplicate rows, a forced failure ends `failed`, and a retry then succeeds.
  - _Requirements: 1.1–1.7, 6.1_
- [x] 9. Read APIs (pages, extractions)
  - Done when: the endpoint tests pass, including cross-org 404s.
  - _Requirements: 5.1–5.3_
- [x] 10. Frontend: investigations, upload, document list with live status, and viewer with boxes
  - Done when: the Vitest tests pass and the Playwright test uploads the 7 samples and sees 48,000 and 68,000.

## Implementation notes (verified 2026-11-23)
- The page and extraction tables shipped in migration 0002 together with the document tables, not in a separate 0003.
- The stage order is parse -> classify -> extract -> validate, because classification needs the parsed text. Per-field Pydantic validation happens inside extract; validate checks what was persisted.
- The provider path is text-only (OpenAI-compatible chat with JSON output), verified with recorded responses. A live provider run is **Blocked** until credentials are configured. Sending page images to a VLM is not implemented yet.
