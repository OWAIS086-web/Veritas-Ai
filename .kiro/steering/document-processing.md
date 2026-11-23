---
inclusion: fileMatch
fileMatchPattern: ["backend/app/services/ingestion/**", "backend/app/services/ocr/**", "backend/app/services/parsing/**", "backend/app/services/extraction/**", "backend/app/services/forensics/**", "backend/app/workers/**"]
---

# Document processing standards

## Ingestion
- Accept PDF, PNG, JPG/JPEG, TIFF, DOCX, XLSX, CSV and EML, plus ZIP archives containing them.
- Check the type from the file's magic bytes, not its extension. Record the detected MIME type and the reason for any rejection.
- Limits come from settings: max file size, max ZIP entries, max ZIP depth (1), max expansion ratio, and max pages.
- Reject ZIP entries with absolute paths, `..` segments or drive letters.
- Compute SHA-256 over the original bytes. A duplicate is the same `(organization_id, case_id, sha256)`.
- Generate storage keys as `{organization_id}/{document_id}/original`. The user's filename is metadata only.
- **Never modify the original.** Derived artifacts (page images, normalized text) use separate keys.

## Pipeline
Upload validation (type, size, ZIP rules, hash, duplicates) happens synchronously in the request. The asynchronous stages are `parse` (text layer, OCR and layout) → `classify` → `extract` (with per-field schema validation) → `validate` (document-level check of what was persisted). The document is then `completed`, or `failed` with the stage and error. Classification runs after parsing because it needs the text.

- Each stage is a Celery task, idempotent on `(document_id, stage, pipeline_version)`. A re-run replaces that stage's own rows inside one transaction, or skips the stage if it is already complete.
- Each stage has a time limit and bounded retries (max 3, exponential backoff), and persists its status in `document_stages`.
- Routing:
  - Digital PDFs use PyMuPDF text and boxes, then Docling for layout and tables.
  - Scanned PDFs and images use OpenCV preprocessing, then PaddleOCR.
  - DOCX, XLSX, CSV and EML use direct parsers. Their fields have a null bbox and a `location` (sheet!cell, paragraph index, header name).

## Provenance per extracted field
`name, value, normalized_value, confidence, document_id, page, bbox [x0,y0,x1,y1 in PDF points], method (text_layer|ocr|vlm|parser), model_version, status (extracted|uncertain)`.

## Normalization
- Amounts become a `Decimal` plus an ISO 4217 currency. Never compare amounts across different currencies.
- Dates become an ISO date plus a semantic role (`invoice_date`, `shipment_date`, ...). Only dates with the same role are compared.
