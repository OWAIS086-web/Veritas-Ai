# Design: Multimodal Document Intelligence

## Components
| Component | File | Responsibility |
|---|---|---|
| Pipeline orchestrator | `app/workflows/document_pipeline.py` | Stage order, idempotency guard, stage records |
| Celery tasks | `app/workers/document_tasks.py` | `process_document`, `run_stage`, with time limits and retries |
| Classifier | `app/services/classification/rules.py` | Weighted keyword and title rules, with an optional provider fallback |
| PDF parser | `app/services/parsing/pdf.py` | PyMuPDF `page.get_text("words")`/`"blocks"`, page size, text-layer detection |
| Layout | `app/services/parsing/layout.py` | Docling conversion (tables), optional, with timeout |
| Office, CSV, email parsers | `app/services/parsing/{docx,xlsx,csv,eml}.py` | Direct parsers with locations |
| OCR | `app/integrations/ocr/paddle.py`, `app/services/ocr/service.py` | OpenCV grayscale, deskew and denoise, then PaddleOCR lines with box and confidence |
| Extractors | `app/services/extraction/{rules,llm,verify,normalize}.py` | Label-based extraction, provider extraction, the anti-fabrication check, normalizers |
| Provider | `app/integrations/llm/{base,openai_compat,replay}.py` | `complete_json(messages, schema)` with timeout, retries and fallback models. The replay provider is for tests. |

## Data model (migration 0003)
- `document_pages(id, organization_id, document_id, page_number, width, height, text, blocks jsonb, method, ocr_mean_confidence, image_key, unique(document_id, page_number))`
- `extraction_runs(id, organization_id, document_id, pipeline_version, method, model_version, provider, prompt_version, status, started_at, finished_at, error)`
- `extracted_fields(id, organization_id, extraction_run_id, document_id, name, value, normalized_value jsonb, value_type, currency, semantic_role, confidence numeric(4,3) null, page_number, bbox jsonb null, location, method, model_version, status, rejection_reason)`

All three tables have RLS.

## Anti-fabrication check (`verify.py`)
`value_is_supported(value, page_text) -> bool`. Both strings are normalized: casefold, collapsed whitespace, unified dashes, and amounts compared as digit sequences with grouping removed. The check returns true only if the normalized value is a substring of the normalized page text. Unsupported values become `null`/`uncertain`.

## Idempotency
`run_stage` reads the `document_stages` row for the key. If `succeeded`, it returns. Otherwise, in one transaction, it deletes the stage's prior outputs for that document and version, writes new outputs, and marks the stage `succeeded`.

## Failure handling
| Failure | Behavior |
|---|---|
| PaddleOCR import or model unavailable | The OCR stage fails with `ocr_unavailable`, and documents that need OCR end `failed` (retryable). Documents with a text layer are not affected. |
| Docling timeout | Tables are skipped, the stage `metrics.layout = "skipped: timeout"` is recorded, and the stage still succeeds |
| Provider timeout or invalid JSON | 2 retries, then the fallback models, then the rules extractor, recorded in the run |
| Worker killed | `acks_late` re-delivers the task, and the idempotency guard prevents duplicate rows |

## Testing
- Unit: each parser on the generated samples; verify (Hypothesis: a value inserted into the text is always supported, and random strings not in the text are not); amount and date normalizers (Hypothesis round trips).
- Integration: the full pipeline on the 7 PDFs through Celery `task_always_eager=False` with a real worker in Compose, or in-process eager mode for CI. Asserts that `total_amount` is 48000 or 68000 per document with page and bbox.
- Replay: provider tests use `tests/fixtures/llm/*.json`. Live tests are marked `live`.
