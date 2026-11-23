# Design: Reporting

## Components
- `app/services/reporting/model.py` defines `ReportModel` (Pydantic) with one field per section. It is built only from database rows.
- `app/services/reporting/builder.py` builds the report from the case, the investigation, findings, evidence, entities, forensics and audit data, giving a `ReportModel`.
- `app/services/reporting/verify.py` is the citation verifier (Req 2.2) and the summary verifier (Req 1.3: extract numbers and ids with a regex and check them against the model).
- Renderers in `app/services/reporting/render/`:
  - `json_renderer.py` uses `model_dump_json`.
  - `xlsx_renderer.py` uses openpyxl, with one sheet per section and the evidence table.
  - `docx_renderer.py` uses python-docx.
  - `pdf_renderer.py` uses ReportLab (justification: pure-Python PDF generation with tables and no system dependencies).
- `app/workers/report_tasks.py` runs build, verify, render, store, and records `report.generated`.

## Data model (migration 0008)
`reports(id, organization_id, case_id, investigation_id null, format, status, storage_key, sha256, model_json jsonb, error, created_by, created_at)`.

## Failure handling
- The verifier fails: the report is `failed` with `error` listing the references, and no file is stored.
- The provider fails for the summary: a deterministic template summary built from the counts is used, and `summary_method=template` is recorded.

## Testing
- Unit: each renderer opens with its library and contains the section headings.
- Verifier: an injected orphan reference fails the export.
- Integration: the demo report cites the 5 evidence documents with the correct pages and the finding id.
