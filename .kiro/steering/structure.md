---
inclusion: always
---

# Architecture and project structure

The full architecture, with diagrams and the dependency matrix, is in #[[file:docs/architecture.md]].

## Shape
A **modular monolith**. One FastAPI application and one Celery worker codebase share the `backend/app` package. Module boundaries are enforced by convention and review:

- `api/v1/*` route handlers parse input, call one service and map the result. No SQL and no business logic in handlers.
- `services/<module>/` hold business logic. Services receive their dependencies (session, storage, providers) through parameters or FastAPI `Depends`.
- `repositories/` hold reusable query logic when it is shared by more than one service.
- `models/` are SQLAlchemy models. `schemas/` are Pydantic API contracts. Never return ORM objects from the API.
- `integrations/` wrap external systems (LLM, OCR, storage, vector, graph) behind small interfaces so they can be swapped.
- `workers/` define Celery tasks, which call services. Tasks are idempotent.

## Module dependencies (a row may only import from the modules listed)
| Module | May depend on |
|---|---|
| core | (nothing in app) |
| identity (auth, orgs, rbac) | core |
| ingestion | core, identity |
| extraction (ocr, parsing, classification) | core, identity, ingestion |
| forensics | core, identity, ingestion |
| doccompare (comparison lab) | core, identity, ingestion, extraction (read-only `document_pages` and `extracted_fields`), forensics (the `imaging` raster and SSIM primitives) |
| entity_resolution | core, identity, extraction |
| comparison | core, identity, extraction, entity_resolution |
| graph | core, identity, comparison, entity_resolution |
| investigation | all of the above, through the permissioned tool layer |
| reporting | core, identity, extraction, forensics, comparison, graph, investigation (read-only use of extraction and forensics: reporting requirement 1.1 has "extracted information" and "forensic observations" sections, and a report must not need an investigation run) |

## Layout
```
backend/app/{main.py, core/, api/v1/, models/, schemas/, repositories/, services/, integrations/, workers/, agents/, workflows/}
backend/{migrations/, tests/, scripts/, openapi.json}
frontend/src/{app/, components/, features/, hooks/, services/, stores/, types/, layouts/, pages/}
infrastructure/{docker/, nginx/}
sample-data/shipment-case/
docs/
scripts/
```

## Data stores
PostgreSQL is the only source of truth. Neo4j and Qdrant (later phases) are derived from it through a transactional `outbox` table and can be rebuilt from it.
