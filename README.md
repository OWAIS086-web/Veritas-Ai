# VERITAS AI

**Autonomous Document Investigation & Truth Intelligence Platform**

*Don't just read documents. Investigate the truth behind them.*

VERITAS AI investigates a set of business documents together. It extracts fields with page and bounding-box provenance, compares documents against each other, connects entities in an evidence graph, runs a bounded multi-agent investigation, and produces cited reports for human review. It never declares a document forged or a party fraudulent. It reports observations, the evidence behind them and their limitations.

> Kiroween 2026 hackathon submission. Category: **Frankenstein** (assumed; see `docs/implementation-progress.md`).

## Status
Development happens phase by phase. The real, verified state of every feature is in [`docs/implementation-progress.md`](docs/implementation-progress.md). Features that are not built yet show "Available in a later phase" in the UI.

| Phase | Scope | State |
|---|---|---|
| 0 | Kiro specs, steering, agents, hooks | Done |
| 1 | Foundation: auth, organizations, RBAC, row-level security, audit log, jobs with SSE | Done |
| 2 | Ingestion and document intelligence: upload validation, PDF/scan/image/Office/CSV/EML parsing, OCR, classification, extraction with page provenance, document viewer | Done (rules extractor only until a model provider is configured) |
| 3 | Cross-document intelligence: deterministic comparison rules, findings with cited evidence and three separate scores, review decisions, Findings Center | Done (optional LLM interpretation not built) |
| 4 | Evidence knowledge graph: entities and relationships in Postgres with database-enforced evidence, synced to Neo4j through an outbox, Intelligence Graph UI (React Flow) | Done |
| 5 | Document forensics: PDF structure (incremental updates, producer history, single-use fonts), localized compression, version comparison, stamp variation. Observations with measured values and stated limitations, never verdicts. Forensics Lab UI with overlays on the page | Done |
| 6 | Autonomous investigation: 8 LangGraph agents with allowlisted read-only tools, citation validation, budgets, Postgres checkpoints and a human-review step before the report. AI Agents screen with the live event log | Done |
| 7 | Evidence Explorer (side-by-side documents at the cited pages with labelled highlights, forensic overlays, assignment and document requests) and Reports (PDF, DOCX, XLSX, JSON from one verified model; every citation re-checked before export; signed, hash-checked downloads) | Done |
| Lab | Document Comparison Lab (Forensics Lab tab): original versus test document with page alignment, OCR and pixel comparison, Qwen2.5-VL region checks, synchronized viewers, review, annotated PDF/PNG, report and JSON downloads | Built and tested; final checks pending |
| 8+ | Remaining specs (see `docs/implementation-progress.md`) | Not started |

Optional local models: set `VERITAS_LLM_BASE_URL` to an OpenAI-compatible server such as Ollama (see `docs/deployment.md`). Every value a model returns is kept only if it is found on the page it cites.

The pipeline and the comparison rules are described in [`docs/ai-pipeline.md`](docs/ai-pipeline.md) and the API in [`docs/api.md`](docs/api.md). To try it, create an investigation and upload the 7 files in `sample-data/shipment-case/`. When processing finishes, the case shows one finding: the declared totals differ by USD 20,000.00, with 5 cited evidence items.

## Quick start (Docker)
Requirements: Docker Desktop (Windows, macOS) or Docker Engine with the Compose plugin (Linux).

```bash
cp .env.example .env          # Windows PowerShell: Copy-Item .env.example .env
# edit .env and replace every CHANGE_ME value
docker compose up -d --build
```

Open http://localhost:8080 and register. The API docs are at http://localhost:8080/api/docs.

The full instructions for Windows and Linux are in [`docs/deployment.md`](docs/deployment.md).

## Repository layout
| Path | Contents |
|---|---|
| `.kiro/` | Kiro specs, steering, custom agents and hooks (see [`docs/kiro-usage.md`](docs/kiro-usage.md)) |
| `backend/` | FastAPI, SQLAlchemy, Alembic, Celery |
| `frontend/` | React, TypeScript, Vite |
| `infrastructure/` | Dockerfiles, Nginx, Postgres init |
| `docs/` | Architecture, deployment, progress, Kiro usage |
| `scripts/` | Smoke test and quality gate (`.ps1` and `.sh`) |

## Pre-existing code disclosure
None. All code in this repository was written during the Kiroween 2026 Submission Period. It uses only standard open-source frameworks and libraries, listed in `backend/pyproject.toml` and `frontend/package.json`.

## Synthetic data
All sample documents in `sample-data/` are fictional and labelled **SYNTHETIC DEMONSTRATION DATA**.

## License
[MIT](LICENSE)
