# VERITAS AI architecture

VERITAS AI is a **modular monolith**. One FastAPI application and one Celery worker codebase share a single Python package (`backend/app`). PostgreSQL is the only source of truth. Neo4j and Qdrant (later phases) are derived views fed by a transactional outbox, so they can be rebuilt at any time.

## System diagram

```mermaid
flowchart LR
  UI[React SPA] -->|REST + SSE| NGX[Nginx]
  NGX --> API[FastAPI modular monolith]
  API --> PG[(PostgreSQL: source of truth)]
  API --> RD[(Redis)]
  API --> S3[(S3 object store: originals + derived artifacts)]
  RD --> CW[Celery workers]
  CW --> OCR[PaddleOCR / Docling / PyMuPDF / OpenCV]
  CW --> LLM[LLM/VLM provider interface]
  CW --> QD[(Qdrant)]
  CW --> N4[(Neo4j evidence graph)]
  CW --> PG
  CW --> LG[LangGraph investigation: 8 agents]
  LG --> LLM
  LG -->|permissioned tools| API
  PG -. outbox sync .-> N4
  PG -. outbox sync .-> QD
```

## Document pipeline (Phase 2)

```mermaid
flowchart TD
  A[Upload] --> B[Validate: magic-byte MIME, size, ZIP limits, path checks] --> C[SHA-256 + duplicate check]
  C --> D[Store original in S3 store, immutable] --> F{Native text layer?}
  F -->|yes| G[PyMuPDF text + bbox]
  F -->|no| H[OpenCV preprocess + PaddleOCR]
  G --> I[Docling layout / tables]
  H --> E[Classify: title and keyword rules]
  I --> E
  E --> J[Extraction: rules, or provider then verify]
  J --> V[Anti-fabrication check: value must appear on cited page]
  V --> K[(extracted_fields)]
  K --> FX[Forensics stage: PDF structure, compression, version, stamps]
  D --> FX
  FX --> FR[(forensic_runs + forensic_anomalies, separate from findings)]
```

## Investigation workflow (Phase 6)

```mermaid
flowchart LR
  P[Planner] --> D[Document] --> F[Forensics] --> X[Cross-Reference] --> E[Entity] --> G[Graph] --> R[Risk] --> H{{Human review interrupt}} --> W[Report]
```

Each agent has a tool allowlist, a Pydantic output model, a maximum iteration count, a timeout and a token budget. A reference validator rejects any cited evidence that doesn't exist. Every step is persisted in `agent_events`.

## Modules

| Module | Location | Responsibility and boundary |
|---|---|---|
| core | `app/core` | Config, security primitives, logging, errors, permission map. No business logic. |
| identity | `app/services/identity` | Users, organizations, memberships, roles, JWT and refresh tokens. Issues the `organization_id` every query filters on. |
| audit | `app/services/audit` | Append-only audit log. |
| jobs | `app/services/jobs`, `app/workers` | Persisted job state, Celery tasks, SSE event streams. |
| ingestion | `app/services/ingestion` | Upload, validation, hashing, duplicate detection, storage. Never modifies originals. |
| classification, ocr, parsing, extraction | `app/services/...` | Document type, text and layout, structured fields. Writes `document_pages` and `extracted_fields` only. |
| forensics (built) | `app/services/forensics`, `app/api/v1/forensics.py` | PDF structure and visual analysis: pure analyses (`pdf_structure`, `visual`, `versions`, `stamps`) orchestrated by `analyze.py`, and `runner.py` as the fifth pipeline stage, after `validate`. It reads the original bytes, the extracted field boxes (to relate regions to values) and the superseded version. Results are stored in `forensic_runs` and `forensic_anomalies`, separate from extraction and from findings. Severity is capped at medium, and every run states its limitations. Depends on core, identity and ingestion, as in the matrix. Reading `extracted_fields` and `documents` rows is the only coupling to extraction. |
| entity_resolution | `app/services/entity_resolution` | Entity normalization and matching. |
| comparison | `app/services/comparison` | Deterministic cross-document rules first, LLM interpretation last. Creates findings and evidence. Pure rules (`rules/*.py`) and engine, plus `persist.py` for the idempotent upsert. It runs at the end of every processing job and on demand (`cases.compare` task). |
| graph (built) | `app/services/graph`, `app/integrations/graph`, `app/workers/graph_tasks.py` | The pure projection (`projection.py`), the Postgres rebuild in the comparison's transaction with an outbox row (`service.py`), the outbox drain and reconciler (`sync.py`) on the worker's embedded beat, and Neo4j (`neo4j_store.py`, namespaced, parameterized Cypher). The API reads Neo4j and falls back to Postgres. Depends on comparison and entity_resolution, as in the matrix below. |
| findings | `app/services/findings` | Review of persisted findings: list, detail, status decisions (evidence rule, required notes), comments. Never creates findings. |
| graph | `app/services/graph` | Neo4j projection of entities and relationships through the outbox. Every edge carries an `evidence_id`. |
| investigation | `app/agents`, `app/workflows` | LangGraph agents that reach services only through permissioned tools. |
| risk | `app/services/risk` | Anomaly score, evidence confidence and investigation priority, kept separate. |
| reporting | `app/services/reporting` | Reports in four formats, citing only persisted evidence. |

## Dependency matrix

A row depends on the columns marked ●.

| Module | core | identity | ingest | extract | forensics | entity | compare | graph | invest | report |
|---|---|---|---|---|---|---|---|---|---|---|
| identity | ● | | | | | | | | | |
| ingestion | ● | ● | | | | | | | | |
| extraction | ● | ● | ● | | | | | | | |
| forensics | ● | ● | ● | | | | | | | |
| entity | ● | ● | | ● | | | | | | |
| comparison | ● | ● | | ● | | ● | | | | |
| graph | ● | ● | | | | ● | ● | | | |
| investigation | ● | ● | | ● | ● | ● | ● | ● | | |
| reporting | ● | ● | | | | | ● | ● | ● | |
| frontend | | ● | ● | ● | ● | | ● | ● | ● | ● |

## Tenant isolation

```mermaid
flowchart LR
  R[Request with JWT] --> A[Auth dependency: user, org, role]
  A --> P[require_permission]
  P --> S[Service query: WHERE organization_id = :org]
  S --> T["Transaction: SET LOCAL app.current_org = org"]
  T --> RLS[Postgres RLS policy as non-owner role veritas_app]
```

The application connects to Postgres as `veritas_app`. That role doesn't own the tables and has no `BYPASSRLS`, so row-level security always applies. Migrations run as the owner role in a separate one-shot container.

## Evidence chain

original file (sha256) → `document_pages` → `extracted_fields` (page, bbox, method, model_version) → `evidence_items` → `findings` → report citation. Graph edges carry an `evidence_id`.

## Key decisions

| Decision | Reason | Alternative rejected |
|---|---|---|
| Modular monolith | One deployable fits the team size and deadline, with clear module boundaries | Microservices (operational cost with no benefit at this scale) |
| RLS plus explicit filters | A missed `WHERE` clause can't leak data | Application filters only |
| Opaque rotating refresh tokens | Can be revoked, and token theft is detected through reuse | Long-lived JWT refresh tokens |
| SSE for progress | One-way, survives proxies, resumes with `Last-Event-ID` | WebSockets (two-way isn't needed) |
| Deterministic comparison first | Reproducible findings. The LLM only interprets. | LLM-first comparison (not reproducible) |
| OpenAI-compatible provider | Covers hosted APIs and local Qwen servers with one interface | A vendor SDK per provider |
