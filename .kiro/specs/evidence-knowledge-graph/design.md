# Design: Evidence Knowledge Graph

## Components
- `app/services/entity_resolution/resolve.py` (pure) turns usable party, shipment-reference and bank-reference fields into entities.
  - Organizations are grouped by normalized name. Pairs are compared within a blocking key (the first token). Pairs at or above `VERITAS_ENTITY_MERGE_THRESHOLD` (0.95) merge. Pairs between `VERITAS_NAME_SIMILARITY_THRESHOLD` (0.85) and the merge threshold stay separate and are flagged `possible_duplicate`.
  - Confidence is `min(similarity, field confidences)`, or null when any field confidence is unmeasured.
  - Entity ids are UUIDv5 of `(case, type, normalized name)`.
- `app/services/graph/projection.py` (pure) builds nodes (documents, entities, findings) and edges. Each edge carries the ids of the extracted fields or evidence items it is based on:
  - `ISSUED_BY`, `ISSUED_TO`, `PAID_BY` and `ASSOCIATED_WITH`: a fixed table of document type × party field.
  - `SHIPPED_UNDER`: the shipment reference.
  - `REFERENCES`: a document citing another document's number.
  - `SUPPORTS`: an evidence item of a finding.
  - `CONTRADICTS`: between documents with different values in one finding, carrying the finding id.
  - Edge ids are UUIDv5, so a rebuild keeps them.
- `app/services/graph/service.py` rebuilds a case's derived rows inside the comparison's transaction (both the end-of-processing comparison and the `cases.compare` task) and writes an `outbox` row in that transaction. Before a document's fields are replaced, its edges are dropped, so no relationship points at deleted evidence.
- `app/integrations/graph/neo4j_store.py` uses the official async neo4j driver. Labels and relationship types come only from allowlists, and all values are bound parameters. A case's subgraph is replaced in one write transaction. Every node and edge carries `ns` (`VERITAS_NEO4J_NAMESPACE`), `organization_id` and `case_id`, and every query filters on all three.
- `app/services/graph/sync.py` and `app/workers/graph_tasks.py`:
  - Rows are claimed through the owner-owned `outbox_claim()` (`FOR UPDATE SKIP LOCKED`; ids only) and processed in the row's tenant session.
  - A failure goes back to pending with exponential backoff. After `VERITAS_OUTBOX_MAX_ATTEMPTS` the row is marked dead and reported in `/system/health`.
  - The reconciler compares node and edge counts per case (through `graph_cases()`), queues a rebuild on drift, and removes Neo4j subgraphs of deleted cases.
  - Both run on Celery beat embedded in the worker (`-B`): drain every 15 s, reconcile every 10 minutes.
- Frontend: `features/graph/GraphPage.tsx`, the lazy-loaded `GraphCanvas.tsx` (React Flow with a dagre left-to-right layout; dagre is justified as a deterministic hierarchical layout), `DetailsPanel.tsx`, and an accessible list view of the same relationships.

## Data model (migration 0004)
- Postgres:
  - `entities(id, organization_id, case_id, type, canonical_name, normalized_name, confidence, status, mention_count, details)`
  - `entity_mentions(id, organization_id, entity_id, extracted_field_id, document_id, field_name, value, page_number, bbox, location, confidence)`
  - `relationships(id, organization_id, case_id, type, source_kind, source_id, target_kind, target_id, evidence_ids uuid[] CHECK (cardinality > 0), finding_id, properties)`. A trigger requires every evidence id to be an `extracted_fields` or `evidence_items` row of the same organization, and `CONTRADICTS` requires `finding_id`.
  - `outbox(id, organization_id, target, op, payload, status, attempts, last_error, available_at, claimed_at, processed_at)`
  - All four tables have RLS. Entities, mentions and relationships are SELECT, INSERT, DELETE; the outbox adds UPDATE.
- Neo4j: nodes `:VeritasNode:Document|Entity|Finding`, edges typed by relationship type, with a uniqueness constraint on `id` and an index on `(ns, organization_id, case_id)`.

## Failure handling
- If Neo4j is unavailable, outbox rows stay pending and the API serves the graph from the Postgres tables (same shape), with `X-Graph-Source: postgres`.
- The API also serves Postgres while a sync for the case is pending, so a response never shows a stale graph.
- Finding review status isn't copied into the graph (it changes outside comparisons). The UI reads it from the finding.

## Testing
- Property tests:
  - Resolution is order-independent and partitions the mentions.
  - Every edge has resolvable evidence and known ends.
  - The projection is deterministic.
- Integration (real Postgres and Neo4j, own namespace):
  - The demo graph: supplier ISSUED_BY, SHIPPED_UNDER, and CONTRADICTS carrying the finding id.
  - Sync, Postgres fallback, outage recovery, dead rows, reconcile.
  - Cross-org 404.
- End to end: the Playwright demo flow, and a real outage check with `scripts/graph-outage-check.ps1`.
