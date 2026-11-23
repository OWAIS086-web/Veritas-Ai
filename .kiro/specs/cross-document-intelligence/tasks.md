# Tasks: Cross-Document Intelligence

- [x] 1. Migration 0003 (findings, evidence, decisions, comments, triggers)
  - Done when: the migration cycle passes, the trigger blocks evidence-less confirmation, and `ai_output_json` is immutable.
  - _Requirements: 5.1, 5.3_
  - Verified by `tests/integration/test_migrations.py` and `test_findings.py::test_database_triggers_and_append_only_tables`.
- [x] 2. Name normalization and similarity
  - Done when: the Hypothesis properties pass (normalization is idempotent, and similarity is symmetric and between 0 and 1).
  - _Requirements: 3.3_
  - Verified by `tests/property/test_names.py`.
- [x] 3. Financial and quantity rules
  - Done when: the property tests pass and the demo case yields a single 20,000 USD finding with no quantity finding.
  - _Requirements: 1.1–1.3, 2.1–2.2, 3.1_
  - Verified by `tests/property/test_comparison_properties.py`, `tests/unit/test_comparison_rules.py` and `test_findings.py::test_demo_case_yields_one_20000_usd_discrepancy_with_5_evidence_items`.
- [x] 4. References, identity, duplicates, dates and missing-document rules
  - Done when: a unit test with fixture fields covers each rule's positive and negative cases.
  - _Requirements: 3.2–3.5, 4.1_
  - Verified by `tests/unit/test_comparison_rules.py`.
- [x] 5. Risk scoring with three separate values
  - Done when: the unit tests pass and no field named or derived as a "fraud probability" exists.
  - _Requirements: 5.1_
  - Verified by `tests/property/test_scoring.py`.
- [x] 6. Findings service, idempotent upsert and the API
  - Done when: a re-run keeps human statuses, the 409 without evidence holds, and cross-org returns 404.
  - _Requirements: 5.2, 5.3_
  - Verified by `test_findings.py` (re-run, review decisions, isolation) and `test_rbac_matrix.py`.
- [x] 7. Findings Center UI
  - Done when: the list, filters and status change work against the real API, with tests.
  - Verified by `src/features/findings/findings.test.tsx` and the Playwright demo flow in `tests/e2e/documents.spec.ts`.

## Not in this phase
- Requirement 6 (optional LLM interpretation of undecidable cases) is not implemented. No model credentials are configured, and the rules decide every case in the demo.
- Outbox events to the graph (`evidence.graph.updated`) arrive with the evidence-knowledge-graph spec.
