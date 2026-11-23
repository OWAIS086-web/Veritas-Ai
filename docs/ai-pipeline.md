# Document intelligence pipeline (Phase 2)

## Flow
1. **Upload** (synchronous, in the request): content-based type detection (magic bytes and structure, never the extension), size limit, ZIP rules (entries, total size, compression ratio, nesting, encryption, unsafe paths), SHA-256, duplicate check per case, new version detection by filename. The original is written once to the S3 store at `{org}/{document}/original`. A `document.process` job is queued after the transaction commits.
2. **parse** (Celery worker): PyMuPDF words with boxes for text-layer pages. Pages without a text layer and image files are rendered and preprocessed with OpenCV (median denoise, projection-profile deskew), then read by PaddleOCR (PP-OCRv5 mobile models, CPU). OCR boxes are mapped back through the inverse deskew transform into page coordinates. Docling extracts tables from text-layer PDFs (its own OCR is disabled). DOCX, XLSX, CSV and EML use direct parsers with locations. TIFF frames are also stored as derived PNGs for display.
3. **classify**: title (first 3 lines) and keyword rules. The score is a rule-match ratio, not a probability. Weak evidence gives `unknown`.
4. **extract**: the deterministic label-based extractor always runs. If a provider is configured (`VERITAS_LLM_*`), the model is asked for the same fields, with document text only inside `<document_data>` blocks. Every claimed value must occur on the page it cites, or it becomes `null` / `uncertain` with `value_not_on_cited_page`. Box and confidence always come from that page's tokens. Where a model claim is rejected, a verified rules value may stand in, and each field records its method. Values are normalized (Decimal plus ISO 4217 currency, ISO dates with a semantic role, quantities, name and reference keys) and validated with Pydantic before persistence.
5. **validate**: a document-level check that every persisted `extracted` field has a value, a page or location, and a normalized value.

Each stage is idempotent on `(document_id, stage, pipeline_version)`. It retries up to `VERITAS_STAGE_MAX_ATTEMPTS` with exponential backoff, except for input errors (an unreadable file, for example), which fail at once. A retry resumes from the failed stage.

## Provenance stored per field
`name, value (as printed), normalized_value, value_type, currency, semantic_role, confidence (text layer 1.0 / PaddleOCR score / null), page_number, bbox [x0,y0,x1,y1] top-left origin in PDF points (or pixels for images), location (sheet!cell, paragraph, header, body line), method (text_layer | ocr | parser | llm), model_version, status (extracted | uncertain), rejection_reason`.

## Measured on the synthetic package (2026-11-23)
Windows 11 host, Docker Desktop (8 GB, 16 CPUs), CPU-only worker with concurrency 1. Figures come from the `duration_ms` persisted in `document_stages` for the 28 PDF documents processed in this session's end-to-end and smoke runs. Model warm-up is excluded.

| Stage / path | n | mean | p95 | mean per page |
|---|---|---|---|---|
| parse, text-layer PDF (PyMuPDF + Docling tables) | 25 | 2,045 ms | 3,039 ms | 1,721 ms |
| of which Docling table extraction | 25 | 1,996 ms | | |
| parse, scanned PDF (OpenCV + PaddleOCR, 200 dpi) | 3 | 12,013 ms | 13,385 ms | 12,013 ms |
| classify | 28 | 29 ms | 46 ms | |
| extract (rules) | 28 | 60 ms | 92 ms | |
| validate | 28 | 20 ms | 30 ms | |

Other observations from the same session:
- The full 7-document case went from upload to all completed in about 22 s with a warm worker.
- First worker start downloads and loads the models: PaddleOCR in 14 s, Docling in 155 s. The cache lives in the `models` volume.
- A clean deployment (fresh volumes, including the model cache) became healthy in 384 s.
- Success rate: 28 of 28 PDF documents completed. Every format variant (scanned PDF, PNG, JPG, TIFF, DOCX, XLSX, CSV, EML) completed in the integration suite.

Model provider inference time hasn't been measured, because no provider is configured (see the progress document). These are measurements on one machine with synthetic documents, not capacity claims.

# Cross-document comparison (Phase 3)

Comparison runs at the end of every processing job for each case the job touched, and on demand through `POST /cases/{id}/compare`. It reads the fields of each completed document's latest extraction run. Only fields with `status = extracted` and a normalized value are compared. Uncertain or missing fields are listed in the finding's `coverage.skipped`, with the reason. No model is called: every finding comes from a deterministic rule, recorded as `detected_by = rule_id@version`, and `ai_output_json.detector = "rules"`.

| Rule | Compares | Finding | Severity |
|---|---|---|---|
| `financial.total_amount` | `total_amount` within one currency. Reported when `(max − min) / max` exceeds `VERITAS_AMOUNT_TOLERANCE` (default 0.005). | `financial_discrepancy`, `difference = max − min`, every value cited | ≥ 10% high, ≥ 2% medium, else low |
| `financial.currency` | Totals stated in different currencies (never compared with each other) | `currency_mismatch` | info |
| `quantity.total_quantity` | `total_quantity` within one unit | `quantity_mismatch` | as for amounts |
| `references.match` | Shipment reference; invoice, PO and bill-of-lading numbers against the references other documents make to them (normalized keys) | `conflicting_reference` | medium |
| `identity.parties` | Supplier and buyer names. Reported when the lowest pairwise token-sort similarity after removing legal suffixes is below `VERITAS_NAME_SIMILARITY_THRESHOLD` (0.85). | `identity_mismatch` | medium |
| `duplicates.documents` | Identical SHA-256, or the same document number on files with different content | `duplicate_document` | low or medium |
| `dates.same_role` | Dates with the same semantic role only | `date_inconsistency` | medium |
| `dates.order` | Payment before invoice, shipment before order | `date_inconsistency` | info |
| `missing.expected_documents` | For `international_shipment` cases: PO, invoice, packing list, bill of lading, customs declaration and payment receipt. It doesn't run while documents are still processing. | `missing_document`, `evidence_status = absence` | medium |

Each finding stores three separate values:
- `anomaly_score` is the magnitude.
- `evidence_confidence` is the lowest measured confidence of the cited fields, or null.
- `priority` comes from severity and confidence. It is lowered one level when the confidence is below 0.9 or not measured.

Limitations are stated on the finding. On the demo case, the rule reports the invoice's FOB terms and the customs declaration's CIF valuation basis, and notes that an insured value can legitimately exceed the invoice value. A finding never states that a document is forged or that a party acted fraudulently.

## Result on the synthetic shipment case
Exactly one finding: `financial_discrepancy`, USD 20,000.00, with 5 evidence items. The purchase order, invoice and receipt state USD 48,000.00 (page 1 each). The customs declaration states USD 68,000.00 on page 2, and the insurance certificate USD 68,000.00 on page 1. Anomaly score 0.294, evidence confidence 1.000 (text layer), severity high, priority high. All quantities are 1,000 units, so there is no quantity finding. The names "Global Trading Ltd" and "GLOBAL TRADING LIMITED" normalize to the same key, so there is no identity finding.

## Measured (2026-11-23)
19 comparison runs on the Docker stack (2- to 7-document cases) took 75 ms on average and 159 ms at most, from `comparison_started` to `comparison_completed`, including the database writes.

# Live model provider run (2026-11-23)
Provider: local Ollama 0.40 (OpenAI-compatible API), model `qwen2.5:7b-instruct`, fully in GPU memory. Temperature 0, JSON mode, prompt `extract-v1`. The worker reached it at `http://host.docker.internal:11434/v1`.

| Set | Documents | Extract stage (model call + verification) | Invalid model outputs | Claims rejected by verification |
|---|---|---|---|---|
| Shipment case (text-layer PDFs) | 7 | 1.7–2.8 s each (two runs) | 0 | 1: the insurance certificate's `total_amount` |
| Format variants (scanned PDF, PNG, JPG, TIFF via OCR; DOCX, XLSX, CSV, EML via parsers) | 8 | 1.7–2.1 s each; 7.4 s for the scanned PDF | 0 | 0 |

**The rejected claim:** the model returned `68000.00` for a value printed as `USD 68,000.00`, which breaks the prompt's "copy exactly as printed" rule. Verification rejected it (`value_not_on_cited_page`). The verified rules value took its place, and the run notes record it (`llm_rejected: {"total_amount": "value_not_on_cited_page"}`, `replaced_by_rules: ["total_amount"]`). The run is deterministic at temperature 0: the second run rejected the same claim.

The comparison result is unchanged with the model path: one `financial_discrepancy` of USD 20,000.00 with 5 evidence items. On the format variants, the comparison reported the three invoice copies (one number, three files) and the receipt in two formats as duplicates, and the customs declaration as missing.

`tests/live/test_live_provider.py` (`pytest -m live`, 7 passed in 17 s) checks the same 7 documents directly against the provider. Every value that passes verification matches the ground truth, and every rejected value carries a reason. Page-image extraction with the vision model (`qwen2.5vl:7b`) is not implemented; the provider receives text only.

# Document forensics (Phase 5)

Forensics is the fifth processing stage, after `validate`. It reads the original bytes, never modifies them, and stores its results in `forensic_runs` and `forensic_anomalies`, separate from extraction. No model is called. Every anomaly comes from a measured value, and that value is stored in the anomaly's `metrics`. An anomaly is an observation for review. It never creates a finding, and its severity is at most `medium`. Every run carries the limitation "A visual or structural inconsistency alone does not establish document alteration or forgery." The full design is in `.kiro/specs/document-forensics/design.md`.

| Analysis | Applies to | Anomalies |
|---|---|---|
| PDF structure (PyMuPDF and a byte scan) | PDFs | `incremental_update` (low), `metadata_inconsistency` (medium if the producer changed between revisions, low if the modification date is before the creation date), `font_inconsistency` (medium, a single-use font over an extracted amount, reference, quantity or date) |
| Compression (OpenCV) | Scanned pages and images. Rendered vector pages are recorded as `not_applicable`. | `localized_compression_anomaly`: background noise in 32 px blocks drops to less than half the page median, with z < −6 |
| Version comparison (ECC or ORB alignment, SSIM) | A document that supersedes an earlier upload with the same filename | `version_difference` (medium over an extracted field, low elsewhere) |
| Stamps and signatures (HSV ink mask, contours) | PDFs and images | `stamp_appearance_variation` (medium): `unmatched_ink` against a stamp of compatible size and colour on another document of the case is above 0.004 |

## Calibration on the forensic fixtures (SYNTHETIC DEMONSTRATION DATA)
`sample-data/forensics` is generated deterministically by `backend/scripts/generate_forensics_samples.py`. `manifest.json` records each file's hash, the planted regions and the expected anomaly types.

| Signal | Altered fixture | Unaltered |
|---|---|---|
| Version comparison: local SSIM of the changed total | 0.201 | Other candidate components 0.50–0.71, all rejected by the 0.45 cut-off |
| Stamp comparison: `unmatched_ink` | 0.0112 | Same stamp 0.0, re-scanned stamp 0.0001 |
| Compression: blocks below the noise cut-off | The re-encoded region over the total | None on the clean scan |

Rejected alternatives, as measured:
- An 8×8 DCT blockiness score didn't separate the fixtures. The rendered vector text alone reached z 7.34. It is kept as a recorded metric only.
- SSIM of 96 px stamp masks ranked the altered stamp (0.969) above an honest scan of the same stamp (0.936).

Result through the real pipeline (`tests/integration/test_forensics.py`): every fixture yields exactly its expected anomaly types. Each region overlaps its planted change, and each field reference resolves to an `extracted_fields` row of the same document. The clean invoice, the clean scan and the receipt with the same stamp yield no anomaly. The seven shipment-case PDFs also yield no anomaly, so they serve as negative controls.

Limits:
- The thresholds were calibrated on synthetic documents only. Real scans, re-saved PDFs and signing tools produce incremental updates and producer changes for legitimate reasons.
- Stamps are compared only within one case.
- Signatures are located but never compared or judged.
