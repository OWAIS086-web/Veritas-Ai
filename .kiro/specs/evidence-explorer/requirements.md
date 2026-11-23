# Requirements: Evidence Explorer and Human Review

## Requirement 1: Viewer
1. THE SYSTEM SHALL render PDFs with PDF.js, with page navigation, zoom, text search, an OCR text overlay toggle, and bounding boxes for extracted fields.
2. WHEN a finding is opened THE SYSTEM SHALL open each evidence document at its page and highlight its bbox. Supporting evidence is cyan and conflicting evidence is red, each with a label.
3. THE SYSTEM SHALL provide a side-by-side comparison of two documents, each scrolled to the evidence page.
4. THE SYSTEM SHALL show forensic anomaly overlays when the forensics toggle is on.
5. Non-PDF formats SHALL show their parsed view (image with boxes, table for XLSX/CSV, headers and body for EML) with the evidence location highlighted.

## Requirement 2: Review
1. Finding statuses: `new, under_review, confirmed_observation, needs_more_evidence, dismissed, resolved`.
2. WHEN a reviewer changes the status THE SYSTEM SHALL require a note for `dismissed` and `confirmed_observation`, append a `finding_decisions` row, and leave `ai_output_json` unchanged.
3. WHEN a finding has no evidence items THE SYSTEM SHALL refuse `confirmed_observation` (409), and the UI SHALL explain why.
4. Users can assign an investigator, comment, and request additional documents.
5. The decision history is shown with actor and timestamp.

## Requirement 3: Access
1. Every page image and file the viewer loads SHALL come from signed URLs and SHALL be audited.
