# Design: Reporting (as built, Phase 7)

## Components
- `app/services/reporting/model.py` defines `ReportModel` (Pydantic), with one field per section in the order of requirement 1.1. `SECTIONS` holds the field and heading pairs.
- `app/services/reporting/builder.py` (`build_report`) reads only persisted rows:
  - the case, its documents and their latest extracted fields;
  - the findings with their evidence;
  - the forensic runs, entities and relationships (Postgres graph);
  - the evidence requests;
  - optionally an investigation, only if it is completed and was approved (requirement 3.2, otherwise 409).

  It adds the "SYNTHETIC DEMONSTRATION DATA" label when a page of the case carries that mark (product rule 13).
- **Executive summary** (requirement 1.3):
  - The default is a template built from the counts and titles in the model (`summary_method = "template"`).
  - If the included investigation's report draft has a verified, model-written summary, it is re-checked against this report's content and used (`investigation_model`). If any of its numbers or ids are missing from the content, the template stays and `summary_note` says why.
- `app/services/reporting/verify.py` runs just before rendering.
  - `verify_report` re-resolves every finding, document, page, field, entity, relationship and anomaly id in the model. It uses the same validator as the investigation agents (`app.agents.references`).
  - It also rejects any number or id in the summary that is absent from the structured content.
  - Any problem fails the export with the list of problems (requirement 2.2).
- `app/services/reporting/render.py` renders all formats from one layout (`layout()`: sections of paragraphs and tables):
  - JSON uses `model_dump_json`.
  - XLSX uses openpyxl: a "Report" sheet plus one sheet per tabular section.
  - DOCX uses python-docx.
  - PDF uses **PyMuPDF's HTML layout (`Story`)**.
- `app/services/reporting/service.py` (`generate`, run by the Celery task `reports.generate`) does build → verify → render → store → hash. The file is written once under a server-generated key that is new for each attempt: `{org}/{report_id}/derived/report-{random}.{ext}`.
- `app/api/v1/reports.py`:
  - `POST /cases/{id}/reports`, `GET /cases/{id}/reports`, `GET /reports/{id}`, `GET /reports/{id}/download` (a signed link with a 60 s lifetime).
  - `GET /report-files/{token}` re-checks the stored file's SHA-256 before serving it.

  Report tokens carry the artifact type `report-file`. The document file endpoint refuses them, and the report endpoint refuses document tokens.

## Data model (migration 0007)
The spec's 0008 number was corrected: Phase 6 took 0006.

- `reports`: `id, organization_id, case_id, investigation_id null, format, status (queued|running|completed|failed), storage_key, sha256, size_bytes, model_json jsonb, error, created_by, created_at, finished_at`.
- `CHECK (format IN ('pdf','docx','json','xlsx'))`.
- `CHECK (status <> 'completed' OR (storage_key IS NOT NULL AND sha256 IS NOT NULL))`.
- RLS is enabled. `veritas_app` is granted SELECT, INSERT and UPDATE (no DELETE).

## Failure handling
- **The verifier fails:** status `failed`, with `error` listing each bad reference (for example `document_not_in_case: {...}`). No file is stored, and the download returns 409.
- **The investigation summary is unsupported:** the template summary is used, `summary_method` stays `template`, and `summary_note` gives the reason. The design originally assumed a fresh provider call. None is made: the investigation already produced a verified summary, and a second model call would add cost without adding facts.
- **Unexpected error:** status `failed` with `internal error (<type>)`. Only the error type is logged, because messages can contain document values.

## Deviations from the design text
- **PDF renderer:** PyMuPDF instead of ReportLab. PyMuPDF is already a dependency, renders HTML tables, and needs no system packages. ReportLab would have been a new dependency for the same result.
- **Storage call:** the file is written with `put_derived`, because `put_new` is reserved for uploaded originals. Nothing is overwritten, since each attempt has its own key, and the hash is checked on download.

## Testing
- `tests/unit/test_report_render.py`: each format opens with its library, has every heading in order, and carries the finding id, the evidence document, page and value, and the synthetic label. Hostile text is escaped in the PDF.
- `tests/integration/test_reports.py` (7 tests):
  - the demo report in all 4 formats cites the 5 evidence documents on their pages (PO 1, invoice 1, customs declaration 2, insurance 1, receipt 1) with the finding id;
  - downloads are signed, hash-checked and audited;
  - review labels follow decisions;
  - an orphan reference and an invented summary number each fail the export;
  - an investigation is included only after approval, bringing its hypotheses and verified summary;
  - report and document links can't stand in for each other;
  - cross-org 404 and RLS.
- Vitest: `features/reports/reports.test.tsx`.
- Playwright: `tests/e2e/explorer-reports.spec.ts` generates a PDF on the stack and downloads it, starting with `%PDF-`.
- Smoke: a PDF report's download matches its recorded SHA-256.
