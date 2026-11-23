# Requirements: Investigation Reports

## Requirement 1: Content
1. Reports SHALL contain, in order: title, investigation id, organization, objective, executive summary, scope, documents analyzed, entities identified, extracted information, identified discrepancies, forensic observations, evidence references, relationship analysis, missing supporting documents, alternative explanations (marked as hypotheses), recommended human review, limitations, and audit information.
2. Every discrepancy SHALL cite its finding id, and every evidence reference SHALL cite the document id, original filename, page number and value.
3. The executive summary MAY be written by the provider from the persisted structured content. It SHALL NOT introduce numbers or references absent from that content, and a verifier SHALL reject any number or id in the summary that doesn't appear in the structured content.

## Requirement 2: Formats and generation
1. `POST /cases/{id}/reports` with `{format: pdf|docx|json|xlsx, investigation_id?}` creates a report job. All formats render from the same JSON model.
2. Before export, the citation verifier SHALL re-resolve every `(finding_id, document_id, page)` for the same organization and case. Any orphan SHALL fail the export with the list of bad references.
3. The report file is stored with its SHA-256. `GET /reports/{id}/download` uses a signed URL and is audited.
4. `GET /cases/{id}/reports` lists the history with the format, the status, the review status of the included findings, and the creator.

## Requirement 3: Review status
1. The report SHALL show each finding's human review status and SHALL label unreviewed findings "Not yet reviewed".
2. Reports built from investigations SHALL be generated only after approval.
