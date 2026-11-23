# Design: Evidence Explorer (as built, Phases 2, 3 and 7)

## Components
- **Viewer** (Phase 2): `features/viewer/PdfCanvas.tsx` (PDF.js) and `ImageCanvas.tsx`, with overlay boxes positioned by `overlay.ts` (`toCssRect`, `fitScale`).
  - The bbox is in PDF points (pixels for images) with a top-left origin, scaled by the viewport.
  - The viewer reads the PDF bytes itself with the `X-Veritas-Viewer` header, so download managers don't intercept them.
  - `DocumentViewer.tsx` adds page navigation, zoom, text search, the OCR or text-line overlay, the extracted fields panel and the **forensic overlay toggle** (Phase 7), which draws anomaly regions labelled "Forensic observation (severity)".
- **Parsed views** (Phase 2): `ParsedView.tsx` renders DOCX, XLSX, CSV and EML lines with their locations and highlights the evidence location.
- **Compare view** (Phase 7): `features/explorer/EvidenceExplorerPage.tsx` at `/evidence?finding=…&left=doc:page&right=doc:page`. The URL holds the state, so a comparison can be shared and reloaded.
  - Each pane is a `features/viewer/PageView.tsx`: a document page with boxes, its own page navigation and zoom, and the parsed view for formats without page geometry.
  - **Box colours:** supporting evidence is cyan (`evidence` tone) and conflicting evidence is red (`danger` tone). Each box is labelled "Supporting: …" or "Conflicting: …", and a legend shows both, so role isn't shown by colour alone.
  - **Default panes:** a supporting document is put against a conflicting one. When every value conflicts, as in an amount mismatch where the rule marks all cited values conflicting, the right pane opens a document whose value differs from the left one (USD 48,000 against USD 68,000 in the demo).
- **Review panel** in `features/findings/FindingDetailPage.tsx`:
  - status decisions with required notes and the evidence rule (Phase 3);
  - comments and the decision history (Phase 3);
  - **assignment** to a member of the organization, and **document requests** for the finding (Phase 7);
  - a link from the evidence table to the compare view.
- **Backend** (findings service):
  - `PATCH /findings/{id}/status` and `POST /findings/{id}/comments` (Phase 3).
  - `PATCH /findings/{id}/assignee` (`findings:assign`; the assignee must be a member, otherwise 422; audited `finding.assign`).
  - `POST /findings/{id}/evidence-requests` (`findings:comment`; shown on the finding, on the case and in reports; audited `finding.request_evidence`).
  - Migration 0007 adds `findings.assignee_user_id` and `evidence_requests.finding_id`.

## Data flow
Finding → `GET /findings/{id}` (evidence included) → for each pane, `GET /documents/{id}` and `GET /documents/{id}/preview` (a signed URL, audited as `document.access`) → the canvas loads the file → boxes are drawn from the evidence bboxes on the current page.

## Failure handling
- **Expired signed URL:** the canvas reports a 403, or an image load error, to its parent once (`onExpired`). The parent fetches a new link and the canvas retries. A second failure shows the error. This was found in Phase 7: cached links older than 60 s made viewers stick on "HTTP 403". Regression test: `features/viewer/expiry.test.tsx`.
- **No bbox** (non-PDF formats): the parsed view highlights the evidence location.
- **409 on confirm:** the UI explains that a finding without evidence can't be confirmed.

## Testing
- Vitest:
  - overlay scaling;
  - required-note validation and the 409 message;
  - `features/explorer/explorer.test.tsx` (panes at the cited pages, the legend, roles, the empty and absence states, assignment and document requests, permissions);
  - `features/viewer/expiry.test.tsx`.
- Integration: `tests/integration/test_review_actions.py` (membership check, audit, requests on the finding, case and report, cross-org 404).
- Playwright: `tests/e2e/explorer-reports.spec.ts`. It opens the demo finding side by side and checks for labelled "Conflicting" boxes in both panes, with different values, and no refused link. It then opens the customs declaration at page 2, where the USD 68,000.00 box sits.
