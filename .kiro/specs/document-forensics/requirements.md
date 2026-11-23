# Requirements: Document Forensics

## Introduction
An independent analysis of document structure and visual integrity. It produces anomalies for review, never verdicts.

## Requirement 1: PDF structure
1. THE SYSTEM SHALL record PDF metadata (producer, creator, creation and modification dates), the incremental update count (`%%EOF` markers and xref sections), embedded fonts per page, image count, annotation and form-field counts, and signature-field presence.
2. WHEN the modification date precedes the creation date, or the producer differs between incremental revisions, THE SYSTEM SHALL emit a `metadata_inconsistency` anomaly (low or medium).
3. WHEN a page region uses a font that appears nowhere else in the document and overlaps an extracted amount or reference THE SYSTEM SHALL emit `font_inconsistency` with the region bbox.

## Requirement 2: Visual analysis (OpenCV)
1. THE SYSTEM SHALL render pages at a configured DPI and compute per-region noise variance and JPEG blockiness. A region deviating more than `k` robust standard deviations from the page median SHALL be emitted as `localized_compression_anomaly`.
2. WHEN two versions of a document exist THE SYSTEM SHALL align the pages (ECC or ORB homography), compute SSIM, and emit the regions with SSIM below the threshold as `version_difference`.
3. THE SYSTEM SHALL locate candidate signature and stamp regions (contour plus ink-density heuristics) and compare repeated stamps across documents with SSIM, reporting `stamp_appearance_variation` when the similarity is low.

## Requirement 3: Output
1. Each run SHALL store `{document_id, analysis_type, anomalies:[{type, page, region, severity, explanation, requires_review}], limitations:[...]}` in `forensic_runs` and `forensic_anomalies`, separate from extraction.
2. Every result SHALL include the limitation "A visual or structural inconsistency alone does not establish document alteration or forgery."
3. THE SYSTEM SHALL NOT claim a signature is authentic or forged.
4. A single forensic indicator SHALL NOT raise a finding above `medium` severity.

## Requirement 4: API and UI
1. `GET /documents/{id}/forensics` returns the latest run.
2. The Forensics Lab shows the original page with the anomaly overlays, metadata, structure and an explanation.
