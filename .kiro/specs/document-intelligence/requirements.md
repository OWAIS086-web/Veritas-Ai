# Requirements: Multimodal Document Intelligence

## Introduction
Classification, parsing, OCR, layout and structured field extraction, with full provenance, run as an asynchronous, idempotent pipeline.

## Requirement 1: Pipeline execution
1. WHEN a document is accepted THE SYSTEM SHALL run the stages `classify → parse → ocr → extract → validate` asynchronously in Celery.
2. THE SYSTEM SHALL record each stage in `document_stages` with status, attempts, timings and error.
3. WHEN a stage is re-run for the same `(document_id, stage, pipeline_version)` THE SYSTEM SHALL produce the same rows without duplicates.
4. WHEN a stage fails THE SYSTEM SHALL retry it at most 3 times with exponential backoff, then set the document `failed` with the error.
5. WHEN `POST /documents/{id}/retry` is called on a failed document THE SYSTEM SHALL resume from the failed stage.
6. WHEN `POST /cases/{case_id}/process` is called THE SYSTEM SHALL enqueue every document in the case that is not completed and return a job id whose events report per-document progress.
7. Each stage SHALL have a time limit from settings.

## Requirement 2: Classification
1. THE SYSTEM SHALL classify documents as one of `purchase_order, commercial_invoice, packing_list, bill_of_lading, customs_declaration, certificate_of_origin, insurance_certificate, payment_receipt, supplier_agreement, inspection_certificate, unknown`, with a confidence.
2. WHEN no rule matches with enough confidence and no provider is configured THE SYSTEM SHALL classify as `unknown`, never guess.

## Requirement 3: Parsing and OCR
1. WHEN a PDF page has a text layer THE SYSTEM SHALL extract words and blocks with bounding boxes in PDF points, in reading order (method `text_layer`).
2. WHEN a PDF page has no usable text layer, or the file is an image, THE SYSTEM SHALL render or preprocess it with OpenCV and run PaddleOCR, storing each line's text, box and OCR confidence (method `ocr`).
3. WHEN Docling is available THE SYSTEM SHALL record tables and layout blocks for PDFs.
4. WHEN the file is DOCX, XLSX, CSV or EML THE SYSTEM SHALL parse it directly and record a `location` per block (paragraph index, `sheet!cell`, row/column, or header name), with a null bbox.
5. THE SYSTEM SHALL store one `document_pages` row per page (one logical page for non-paginated formats) and set `documents.page_count`.

## Requirement 4: Structured extraction
1. THE SYSTEM SHALL extract, per document type, the fields defined in `app/schemas/extraction.py` (document number, dates with semantic role, parties, currency, amounts, quantities, references).
2. Each field SHALL carry `name, value, normalized_value, confidence, document_id, page, bbox, location, method, model_version, status`.
3. WHEN a value cannot be found on the cited page's text (after normalization) THE SYSTEM SHALL store `value=null`, `status=uncertain` and `rejection_reason`.
4. THE SYSTEM SHALL normalize amounts to `Decimal` plus ISO 4217 currency, and dates to ISO 8601 plus a semantic role.
5. WHEN a provider is configured THE SYSTEM SHALL send document text only inside a delimited data block, validate the response with Pydantic, and retry invalid output at most 2 times.
6. WHEN no provider is configured THE SYSTEM SHALL use the deterministic label-based extractor and record `method=rules`, `model_version=rules-<version>`.
7. THE SYSTEM SHALL NOT invent confidence. Confidence comes from OCR or the text layer (1.0 for exact text-layer matches) or is null.

## Requirement 5: Read APIs
1. `GET /documents/{id}/pages` SHALL return pages with text, blocks and dimensions.
2. `GET /documents/{id}/extractions` SHALL return the latest extraction run and its fields.
3. All of these SHALL return 404 for another organization.

## Requirement 6: Progress
1. WHEN a client subscribes to `GET /jobs/{id}/events` for a processing job THE SYSTEM SHALL stream per-document stage events, and a reconnect with `Last-Event-ID` SHALL not lose any event.
