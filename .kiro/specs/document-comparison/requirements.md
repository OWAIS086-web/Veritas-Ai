# Requirements: Document Comparison Lab (original versus test)

## Introduction
An investigator compares a test document with an original (reference) document. The system aligns the pages, compares text and pixels, checks the strongest regions with a vision model (Qwen2.5-VL through the OpenAI-compatible provider), and shows every difference on both documents with its evidence, for human review. It reports differences, never verdicts: it never states that a document is forged or authentic.

## Requirement 1: Inputs
1. THE SYSTEM SHALL accept an original and a test file in one multipart request (`original`, `test`) and pass both through the normal ingestion: magic-byte type detection, size limits, SHA-256, duplicate detection and immutable original storage.
2. THE SYSTEM SHALL also compare two existing documents of the same case.
3. Only PDF, PNG, JPEG and TIFF documents SHALL be compared; any other type is refused with a 422 that names the type. Two identical files (the same SHA-256) SHALL be refused with a 409.
4. The comparison SHALL wait until both documents finish the processing pipeline and SHALL fail with the document name when one of them failed.

## Requirement 2: Preprocessing and alignment
1. PDF pages SHALL be rendered at `VERITAS_COMPARISON_DPI`; image files are used at their own resolution; multi-page documents are compared page by page up to `VERITAS_COMPARISON_MAX_PAGES`.
2. Pages SHALL be paired in order. Extra pages SHALL be reported as `page_added` (test) or `page_removed` (original).
3. Each pair SHALL be registered (identity, ECC euclidean coarse-to-fine, ORB+RANSAC homography; the best structural similarity wins) and the method and page SSIM recorded.

## Requirement 3: Text comparison
1. THE SYSTEM SHALL compare the stored text-layer or OCR lines of both documents after mapping the original's tokens onto the test page.
2. A line SHALL differ when its digits differ, when text-layer text differs, or when OCR letter text is less than 85% similar. Changes SHALL be widened to whole words and located with each document's own token boxes.
3. Text with no counterpart SHALL be reported as added or removed. A page without text on both sides SHALL be compared by pixels only.

## Requirement 4: Pixel comparison
1. A pixel SHALL count as changed when local SSIM is below `VERITAS_COMPARISON_SSIM_THRESHOLD`, the gray difference exceeds 40 and the warped original has content there.
2. Changed pixels SHALL be joined into regions; regions under 30 pixels, on the 2% page border, or whose changed pixels have mean SSIM above 0.45 SHALL be discarded as noise.

## Requirement 5: Vision model
1. The vision model SHALL be reached only through the provider interface configured by `VERITAS_LLM_BASE_URL` and `VERITAS_VLM_MODEL`; no model name or endpoint is hardcoded.
2. Region check: the model SHALL see the same region of both documents and answer in a fixed JSON schema. Its answer may raise or lower evidence confidence by 0.10 and SHALL never create a finding.
3. Page scan: a model proposal SHALL become a finding only where changed pixels confirm it (at least 30 pixels and 1% of the box); the stored region SHALL be the tight box of those pixels.
4. Every model box SHALL be validated (ordered, finite, inside the sent image, overlapping the candidate) before use; rejected boxes and proposals SHALL be counted and recorded.
5. Document images are untrusted data: the system prompt SHALL say text in them is never an instruction.
6. WHEN the model is disabled, not configured or unreachable THE SYSTEM SHALL complete the comparison without it and record `vlm_status` (`disabled`, `unavailable`, `failed`). It SHALL stop calling an unreachable model after the first failure.

## Requirement 6: Findings
1. Each finding SHALL store its number (reading order), type, sources (`ocr`, `cv`, `vlm`, `page`), test page and region, original page and region (validated inside each page), the texts, severity (`info`, `low` or `medium`, enforced by the database), evidence confidence in [0.05, 0.95] with the reasons that produced it, an explanation, metrics and the vision-model assessment.
2. Findings SHALL reference the overlapping `extracted_fields` rows of either document.
3. Explanations SHALL describe what each document reads; they SHALL NOT use "forged", "authentic" or "fraud". Every comparison SHALL carry the limitation that a difference doesn't establish either.

## Requirement 7: Review
1. A reviewer (`findings:review`) SHALL set `confirmed_difference`, `needs_more_evidence`, `dismissed` or `unreviewed`; confirming or dismissing requires a note.
2. Each decision SHALL be appended to `comparison_reviews` and audited (`comparison.review`).

## Requirement 8: Outputs
1. THE SYSTEM SHALL generate, from the persisted rows: an annotated copy of the test document as PDF (numbered rectangles plus a numbered list; image files become PDF pages), annotated PNG pages (ZIP), a report PDF with crops of both documents per difference, and a findings JSON.
2. Exports SHALL be generated after completion and on request; dismissed differences are not drawn but stay in the JSON.
3. Regions SHALL be validated against the real page size again before drawing; a region that doesn't fit is skipped and counted.
4. Exports SHALL be stored as derived artifacts with their SHA-256; the stored original is never written to. Downloads SHALL use 60-second signed links that work only on `/comparison-files`, re-check the SHA-256 and are audited.

## Requirement 9: API, security and UI
1. Endpoints are listed in `docs/api.md`. `comparisons:read` and `comparisons:run` come from the permission map; another organization's comparison, finding or export is a 404. The four tables have RLS.
2. Stage and progress SHALL be persisted by the worker and shown in the UI.
3. The Forensics Lab SHALL have a Comparison Lab tab (no new navigation item) with: upload or document selection, the comparison list with live status, synchronized original and test viewers (shared page and zoom, boxes on both), the findings panel with review, downloads, the vision-model status and the measurement summary.
