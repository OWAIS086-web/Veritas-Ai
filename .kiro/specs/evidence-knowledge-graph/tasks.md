# Tasks: Evidence Knowledge Graph

- [x] 1. Migration 0004 (entities, mentions, relationships, outbox)
  - _Requirements: 1.1, 2.2, 3.1_
  - Verified by `tests/integration/test_migrations.py` (cycle, empty model diff), `test_rls.py` (RLS on every new table) and `test_graph.py::test_database_refuses_relationships_without_real_evidence`.
- [x] 2. Entity resolution service
  - Done when: the demo case resolves "Global Trading Ltd" and "GLOBAL TRADING LIMITED" into one entity, and the property tests pass.
  - _Requirements: 1.1–1.2_
  - Verified by `tests/unit/test_entity_resolution.py` (including the order-independence property) and `test_graph.py::test_demo_case_graph_is_backed_by_evidence` (one supplier entity with 7 mentions).
- [x] 3. Relationship projection with the evidence requirement
  - Done when: the property test (every edge has evidence) passes and the CONTRADICTS edge carries the finding id.
  - _Requirements: 2.1–2.3_
  - Verified by `tests/unit/test_graph_projection.py` and the integration test above.
- [x] 4. Neo4j client, outbox worker and reconciler
  - Done when: killing Neo4j mid-sync leaves pending rows and recovery applies them, and a rebuild matches the counts.
  - _Requirements: 3.1–3.3_
  - Verified by `test_graph.py` (outage with retry and backoff, recovery, dead rows, reconcile of drift and of deleted cases) and on the Docker stack with `scripts/graph-outage-check.ps1` (Neo4j container stopped and started again).
- [x] 5. Graph API with the Postgres fallback
  - _Requirements: 4.1–4.2_
  - Verified by `test_graph.py` (Neo4j and Postgres sources, filters, entity and evidence endpoints, cross-org 404) and the RBAC matrix.
- [x] 6. React Flow Intelligence Graph UI
  - _Requirements: 4.3_
  - Verified by `src/features/graph/graph.test.tsx` and the Playwright demo flow.

## Not in this phase
- Entity types `person`, `address`, `bank_account`, `product` and `contract` (requirement 1.1) aren't extracted by the current field catalogue, so no such entities exist yet. Organizations, shipments and transactions are built.
- `BELONGS_TO` and `DERIVED_FROM` are allowed types, but no rule produces them yet.
