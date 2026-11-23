# Design: Evidence Explorer

## Components
- `frontend/src/features/viewer/PdfViewer.tsx` uses `pdfjs-dist`, renders the canvas and a text layer, and overlays an absolutely positioned SVG of boxes scaled by `viewport.scale`. The bbox is in PDF points with the origin top-left (PyMuPDF convention), so it maps directly to PDF.js viewport coordinates after scaling.
- `features/viewer/ParsedViewer.tsx` handles the non-PDF formats.
- `features/explorer/CompareView.tsx` shows two viewers driven by a URL state `?left=doc:page&right=doc:page&highlight=evidenceId`.
- `features/findings/ReviewPanel.tsx` has the status select, a required note, the decision history, comments and assignment.
- Backend: `PATCH /findings/{id}/status`, `POST /findings/{id}/comments`, `PATCH /findings/{id}/assignee` (all in the findings service). The trigger enforces the evidence rule.

## Data flow
Finding click → `GET /findings/{id}/evidence` → for each document, `GET /documents/{id}/preview` (signed URL) → PDF.js loads it → overlays are drawn from the evidence bboxes.

## Failure handling
- An expired signed URL fetches a new one and retries once.
- A missing bbox (non-PDF) highlights the location in the parsed view.
- A 409 on confirm shows "This finding has no linked evidence and cannot be confirmed."

## Testing
- Vitest: the overlay coordinate scaling, the required-note validation and the 409 message.
- Playwright: open the demo finding, verify both documents open on the cited pages and the highlight elements exist.
