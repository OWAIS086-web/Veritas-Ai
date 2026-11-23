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

# Document Comparison Lab (original versus test)

An investigator compares a test document with an original. Every difference is located on both documents and scored; none is called forgery or authenticity. The design is in `.kiro/specs/document-comparison/design.md`.

| Step | Method | Thresholds |
|---|---|---|
| Rasters | PyMuPDF at 144 dpi; image files at their own resolution | up to 20 pages |
| Alignment | identity, ECC euclidean (half size, then full), ORB + RANSAC homography; the highest SSIM wins (a more complex transform must beat a simpler one by 0.002) | 1000 px work width |
| Text | The stored text-layer or OCR lines; original tokens mapped onto the test page; each token joins the test line it overlaps most (≥ 50% of the smaller height); tokens joined by single spaces so layout separators never count | digits must match; text-layer text must match; OCR letter text ≥ 0.85 similar |
| Pixels | local SSIM < 0.6 and gray difference > 40 inside the warped original; 9×9 closing; regions ≥ 30 changed px, off the 2% border, mean SSIM of their changed pixels ≤ 0.45 | |
| Vision (Qwen2.5-VL) | Region check on the 8 strongest candidates (both crops, JSON schema); page scan of the first 3 pages; images sized to multiples of 28 px | ±0.10 confidence; proposals need ≥ 30 changed px and ≥ 1% of the box |

## Measured on `sample-data/comparison` (SYNTHETIC DEMONSTRATION DATA, 2026-11-23)
| Test document | Expected | Found | Notes |
|---|---|---|---|
| `test_altered.pdf` (total, date and IBAN changed) | 3 | 3 | total and IBAN: text + pixels (0.80); date "3"→"8": text only (0.60), its glyph change stays under the pixel thresholds |
| `test_resaved.pdf` (same content, other producer and dates) | 0 | 0 | page SSIM 1.0 |
| `test_scanned_altered.png` (page 1 printed and scanned: 1.2° rotation, 14/−9 px shift, noise) | total, date, missing page 2 | exactly those 3 | ECC alignment, page SSIM 0.983; both boxes fall inside the ground-truth boxes; OCR text compared |

Before the line-assignment fix, each test line took the original tokens inside a fixed window, and on the scan two lines took their neighbours' text (two false "changed" findings). Before the region fix, SSIM was averaged over the whole bounding box (0.51 for the changed total) instead of over the changed pixels (0.18), and the change was missed. Both cases are now unit tests.

## Live vision model (local Ollama `qwen2.5vl:7b`, 2026-11-23)
- Altered invoice: 4 calls, 25.6 s, 9,750 provider-reported tokens. All 3 region checks saw the difference and read the same values as the text comparison ("48,000.00" → "68,000.00", "5407" → "9907", "3" → "8").
- Its boxes were not usable: region-check boxes lay outside the sent crop (for example `[205, 308, 974, 658]` for a crop a few hundred pixels wide), and page-scan boxes were 30–40 px below the changed text, so pixel verification rejected both proposals. This is why the model can only adjust confidence and why every region comes from text boxes or changed pixels.
- On the scan: 3 calls, 15.5 s, 7,387 tokens, the same agreement, 2 boxes rejected and 2 proposals without pixel evidence.
- Replayed in `tests/fixtures/llm/doccompare_vision_altered.json` (recorded from this run); the live check is `tests/live/test_live_doccompare.py`.

# Autonomous investigation (Phase 6)

A LangGraph workflow of eight agents runs in the worker: Planner → Document Intelligence → Forensics → Cross-Reference → Entity Resolution → Evidence Graph → Risk Assessment → human review → Report Generation. The design is in `.kiro/specs/autonomous-investigation/design.md`.

The safety rules hold in code, not only in prompts:
- **Facts come from tools.** Each agent first reads its facts through the tool gateway, which allows only that agent's allowlisted read-only tools and scopes every read to the case. The model is shown those facts as JSON.
- **Page text is fenced as data.** Page text goes only into `<document_data>` blocks in the user message. The system message states that such text is data and never instructions.
- **The model can't act directly.** It answers with JSON validated by a Pydantic model, with at most two retries. It can ask for more allowlisted reads, at most 3 per round, and each round costs an iteration. It can't call tools on its own. Writing tools can't be requested, and an unknown or unlisted tool is refused and recorded.
- **Citations are checked.** Every cited id is checked against the same organization and case. Invalid ones are removed (`reference_rejected`). A statement left without citations is marked `supported: false`.
- **Agents don't change findings.** There is no tool for it. The Risk agent's judgements sit next to the finding's persisted anomaly score, evidence confidence and priority, which are copied unchanged. Alternative explanations are marked as hypotheses. No agent outputs a probability of fraud.
- **The report waits for approval.** It is drafted only after a reviewer approves. A number or id in its executive summary that isn't in the structured content causes the summary to be replaced.

## Live run (2026-11-23, local Ollama `qwen2.5:7b-instruct`)
The case was the invoice (USD 48,000) and the customs declaration (USD 68,000). Comparison gave 5 findings: one financial discrepancy and four missing documents.

| Run | Path | Outcome | Iterations | Tool calls | Tokens | Seconds to review |
|---|---|---|---|---|---|---|
| 1 | live pytest | awaiting_review | 7 | 27 | 17,050 | 34.5 |
| 2 | live pytest (after the planner example change) | awaiting_review | 7 | 27 | 17,584 | 27.6 |
| 3 | live pytest | awaiting_review | 7 | 27 | 14,986 | 24.4 |
| 4 | browser on the stack | awaiting_review; Risk failed (3 invalid outputs) | 7 | 27 | 19,752 | 28 |
| 5 | live pytest (after the tool-request shape fix) | awaiting_review | 10 | 32 | 21,488 | 32.2 |
| 6 | browser on the stack, then approved | completed | 10 | 33 | 22,539 | 46 |

What the safety layer caught on real model output:
- **Run 1:** 2 citations were removed (`reference_rejected`).
- **Runs 1–3:** each had 2 invalid model outputs (`output_invalid`), and the retry was valid. Run 3's diagnostics show both came from the planner answering with tool requests as bare strings. The source wasn't printed for runs 1 and 2.
- **Run 4:** the Risk agent repeated string tool requests such as `"get_finding_evidence(<id>)"` three times, so the step failed. The failure was recorded and the run still paused for review, with the failure shown on screen.

Prompt changes made in response, measured by the next runs:
- **The planner's example `focus` was a sentence the model copied word for word** (runs 1 and 4). It is now a placeholder, and later runs wrote their own focus.
- **The prompt now shows the object shape of a tool request.** Afterwards the model made valid extra requests: 10 iterations instead of 7, and no Risk failure.
- **The Risk prompt now asks for one assessment per finding.** Before, the model assessed only the evidence-backed discrepancy and skipped the four `missing_document` findings, which were listed as `assessed: false`. Run 6 assessed 5 of 5.

The model's main assessment held: evidence strength moderate to strong, review urgency high, and an alternative explanation that the customs value may be CIF while the invoice is FOB, marked as a hypothesis.

Limits:
- These are 6 runs of one 7B model on one synthetic case. Wording and coverage vary between runs.
- The guarantees are the structural checks above, not the quality of the model's prose.
- Signatures are not judged, and no agent sees images. The vision model path is still not built.
