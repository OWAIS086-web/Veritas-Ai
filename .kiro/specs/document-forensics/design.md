# Design: Document Forensics (as built, Phase 5)

## Components
All analyses are pure functions (bytes in, `AnalysisResult` out) under `app/services/forensics/`, orchestrated by `analyze.py`. Each one runs in isolation: an analysis that raises is recorded in `structure["errors"]`, the others still run, and the run status becomes `partial`. DOCX, XLSX, CSV and EML files get a run with status `not_applicable`.

- `model.py` defines `Anomaly`, which refuses any severity above `medium` in `__post_init__`. It also defines `FieldBox`, `AnalysisResult` and `ForensicReport`, which always inserts the mandatory limitation.
- `imaging.py` renders pages with PyMuPDF at `VERITAS_FORENSICS_DPI` (default 110), up to `VERITAS_FORENSICS_MAX_PAGES`. A page with no text layer and a single image covering at least 80% of it is analysed at the image's native pixels (`source="embedded_image"`). Other pages are rendered (`source="rendered"`). Image files are used directly (`source="image_file"`). It also holds an OpenCV SSIM (Gaussian window, the Wang et al. constants). scikit-image was rejected because it would be one more dependency for a single function.
- `pdf_structure.py` records:
  - the metadata;
  - the `%%EOF` and `startxref` counts;
  - each incremental revision with its own producer and modification date, recovered by reopening the byte prefix up to each `%%EOF`;
  - fonts, embedded fonts, images, annotations and form fields per page;
  - signature fields and encryption.

  It emits these anomalies:
  - `incremental_update` (low): more than one save.
  - `metadata_inconsistency` (medium): the producer changes between revisions.
  - `metadata_inconsistency` (low): the modification date is earlier than the creation date.
  - `font_inconsistency` (medium): a font used by one span only that overlaps an extracted amount, reference, quantity or date. The region is the union of the span box and the field box.
- `visual.py` looks for localized compression on embedded raster pages only. For a rendered vector page the result is recorded as `not_applicable`, because rendering noise is not evidence. The method:
  - computes the median absolute deviation (MAD) of a high-pass residual (the image minus a Gaussian blur with σ = 1) over flat background pixels (Sobel magnitude < 40) in each 32 px block that is at least half background;
  - flags a block when `z < -k` (`VERITAS_FORENSICS_NOISE_K`, default 6) and its noise is below half the page median, so a region whose sensor noise was smoothed away by re-encoding stands out;
  - groups flagged blocks into connected components and reports components of 2 or more blocks.

  The 8×8 DCT blockiness is recorded as a metric per page and per region. It does not decide anything, because it did not separate the fixtures.
- `versions.py` finds the version that a document supersedes through `document_versions`. It then:
  - renders both versions at a working width of 1000 px;
  - aligns them with `cv2.findTransformECC` (affine), falling back to an ORB plus RANSAC homography;
  - computes an SSIM map and marks a pixel as changed when SSIM < `VERITAS_FORENSICS_VERSION_SSIM` (0.6) and the absolute difference is > 40;
  - keeps components of at least 30 px that don't touch the 2% border and whose local SSIM is ≤ 0.45.

  The result is `version_difference`, medium when the region overlaps an extracted field and low otherwise. A page-count change is also reported as low.
- `stamps.py` builds an HSV ink mask (S > 90, V > 50), applies morphological closing and filters the contours:
  - a stamp has aspect 0.6–1.6, size ≥ 60 px and ink fill 0.04–0.6;
  - a signature has aspect ≥ 2 and fill ≤ 0.35.

  Each stamp is stored as a 192×192 binary ink-mask descriptor (base64 PNG) in `structure.stamps_signatures.regions`. A stamp is compared with the stamps already analysed on other completed documents of the same case, but only when the size (±25%) and hue (±12) are compatible. The comparison metric is `unmatched_ink`: the share of the ink pixels of both masks that have no ink of the other mask within 1 px. It is symmetric and lies in [0, 1]. It raises `stamp_appearance_variation` (medium) above `VERITAS_FORENSICS_STAMP_THRESHOLD` (0.004). SSIM is still recorded for each comparison.
- `runner.py` loads the field boxes of the latest extraction run, the superseded version and the case's other stamps. It runs `analyze_document` in a worker thread and replaces the document's run for its `pipeline_version` in one transaction.
- `workflows/document_pipeline.py` adds the stage: `STAGES = parse, classify, extract, validate, forensics`.
- `queries.py` and `api/v1/forensics.py` expose two endpoints, both with permission `forensics:read`. Every query filters on `organization_id`, and another organization's ids give a 404.

## Data model (migration 0005)
- `forensic_runs(id, organization_id, document_id, pipeline_version, analysis_types text[], pdf_metadata jsonb, structure jsonb, limitations jsonb, status, started_at, finished_at)`. The column is named `pdf_metadata` because `metadata` is reserved by SQLAlchemy's declarative base. `status` is one of `succeeded`, `partial` or `not_applicable`.
- `forensic_anomalies(id, organization_id, forensic_run_id, document_id, type, page_number, region jsonb, severity CHECK IN ('info','low','medium'), explanation, metrics jsonb, requires_review, created_at)`
- Both tables have RLS. `veritas_app` is granted SELECT, INSERT and DELETE only. Runs are replaced, never updated.

## Severity and findings
- A forensic anomaly is an observation. It never creates a finding: the dependency matrix doesn't allow comparison to depend on forensics.
- The severity is capped at `medium` in three places: `Anomaly`, the API schema and the database CHECK.
- `requires_review` is true for medium anomalies.
- Requirement 3.4 therefore holds by construction.

## Calibration on the synthetic fixtures (`sample-data/forensics`, SYNTHETIC DEMONSTRATION DATA)
| Analysis | Signal | Altered | Unaltered |
|---|---|---|---|
| Compression | min z of the re-encoded region | flagged (z < −6, noise < 0.5 × median) | clean scan: no block flagged |
| Version | local SSIM of the changed total | 0.201 | other components 0.50–0.71, so rejected by 0.45 |
| Stamp | `unmatched_ink` | 0.0112 | same stamp 0.0, scanned copy 0.0001 |

SSIM on 96 px stamp masks was rejected, because the altered stamp scored 0.969 and the honest scan 0.936.

## Deviations from the requirements text
- 2.1: the decision uses a noise *drop* (MAD z-score) rather than a variance rise or JPEG blockiness, because blockiness gave no separation. Blockiness is still recorded.
- 2.3: the decision uses `unmatched_ink` rather than SSIM, for the reason in the calibration section. SSIM is still recorded for each comparison.
- The forensics stage runs after `validate` rather than in parallel with extraction, because the font and version checks need the extracted field boxes.

## Testing
- Unit tests:
  - `tests/unit/test_forensics_structure.py`: structure analysis and date parsing.
  - `tests/unit/test_forensics_visual.py`: compression, versions and stamps on the fixtures, including the overlap of each region with the planted change.
- Property tests (`tests/property/test_forensics_invariants.py`):
  - every report has the mandatory limitation;
  - the severity cap;
  - region geometry.
- Integration tests (`tests/integration/test_forensics.py`):
  - the fixtures go through the real pipeline, and each yields exactly its manifest's expected anomaly types;
  - each region overlaps its planted change;
  - every field reference resolves to an extracted field;
  - the summary order;
  - no findings are created;
  - rerun idempotency;
  - the database refuses a `high` severity;
  - cross-organization 404 and RLS on both tables.
- Frontend tests: Vitest for the Forensics Lab states, and Playwright end to end on the Docker stack.
