# Design: Document Forensics

## Components
- `app/services/forensics/pdf_structure.py` uses PyMuPDF (`doc.metadata`, `page.get_fonts()`, `page.get_images()`, `doc.is_form_pdf`, widgets and annotations) and a raw byte scan for `%%EOF` and `startxref` counts.
- `app/services/forensics/visual.py` uses OpenCV for rendering, block-wise Laplacian variance and 8×8 DCT blockiness, with median and MAD outlier detection.
- `app/services/forensics/versions.py` aligns pages with `cv2.findTransformECC` (falling back to ORB plus RANSAC homography), then computes SSIM (scikit-image `structural_similarity`; justification: the reference SSIM implementation) and thresholded difference contours.
- `app/services/forensics/stamps.py` builds a colour-saturation mask with morphological closing and contour filtering by area and aspect ratio.
- `app/workers/document_tasks.py` adds a `forensics` stage that runs in parallel with extraction after parsing.

## Data model (migration 0005)
- `forensic_runs(id, organization_id, document_id, pipeline_version, analysis_types text[], metadata jsonb, structure jsonb, limitations jsonb, status, started_at, finished_at)`
- `forensic_anomalies(id, organization_id, forensic_run_id, document_id, type, page_number, region jsonb, severity, explanation, metrics jsonb, requires_review)`

## Failure handling
Each analysis type runs independently. A failing analysis is recorded in `structure.errors` and the others still run. Page rendering is limited by `VERITAS_FORENSICS_MAX_PAGES`.

## Testing
- Generated fixtures: a clean PDF, the same PDF with one amount replaced through an incremental update in a different font, and a JPEG-recompressed region.
- Assert: the incremental update is detected, `font_inconsistency` is raised on the replaced region, the compression anomaly region overlaps the edited bbox, and the clean PDF yields no medium or higher anomaly.
- Property: every result contains the mandatory limitation.
