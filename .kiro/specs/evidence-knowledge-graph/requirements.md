# Requirements: Evidence Knowledge Graph

## Introduction
A Neo4j projection of entities, documents, transactions and findings, where every relationship is backed by evidence. It is explored through an interactive React Flow graph.

## Requirement 1: Entities
1. THE SYSTEM SHALL create `entities` (organization, person, address, bank_account, product, shipment, transaction, contract) from extracted fields and `entity_mentions` that link each entity to the `extracted_fields` row it came from.
2. WHEN two mentions normalize to the same name and their similarity is ≥ the threshold THE SYSTEM SHALL merge them into one entity with `confidence = min(similarity, field confidences)`. Merges below the high-confidence threshold SHALL be flagged `possible_duplicate` instead of merged.

## Requirement 2: Relationships
1. Relationship types: ISSUED_BY, ISSUED_TO, REFERENCES, BELONGS_TO, PAID_BY, SHIPPED_UNDER, SUPPORTS, CONTRADICTS, DERIVED_FROM, ASSOCIATED_WITH.
2. Every relationship SHALL carry `evidence_ids` (non-empty) referencing `extracted_fields` or `evidence_items`. THE SYSTEM SHALL refuse to create a relationship without evidence.
3. CONTRADICTS edges SHALL exist only between documents that share a finding, and SHALL carry that finding's id.

## Requirement 3: Synchronization
1. Graph writes SHALL be driven by `outbox` rows written in the same transaction as the Postgres change.
2. A periodic reconciler SHALL rebuild a case's graph from Postgres when drift is detected (node or edge counts differ), and `POST /cases/{id}/graph/rebuild` SHALL trigger it.
3. Every node and edge SHALL carry `organization_id` and `case_id`. Every query SHALL filter on both.

## Requirement 4: API and UI
1. `GET /cases/{id}/graph?types=&q=` returns `{nodes, edges}` with evidence references.
2. `GET /entities/{id}` and `GET /entities/{id}/relationships` return 404 across organizations.
3. The UI supports zoom, pan, search, filtering by entity type, highlighting contradictions, expanding neighbours, showing the evidence behind an edge, and opening the source document at its page.
