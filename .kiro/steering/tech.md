---
inclusion: always
---

# Approved technology stack

Use these technologies. Adding anything else needs a one-line justification in the PR or task notes (what it does that the approved stack cannot).

## Backend (Python 3.12)
| Concern | Choice | Notes |
|---|---|---|
| Web framework | FastAPI | Versioned under `/api/v1` |
| Validation | Pydantic v2, pydantic-settings | All config from env vars |
| ORM | SQLAlchemy 2 (async, asyncpg) | Typed `Mapped[...]` models |
| Migrations | Alembic | Run as the owner role only |
| Database | PostgreSQL 16 | Source of truth, row-level security |
| Cache, broker | Redis 7 | Rate limiting, Celery broker |
| Jobs | Celery 5 | Idempotent tasks, persisted job state |
| Auth | PyJWT, argon2-cffi | HS256 access tokens, opaque refresh tokens |
| Streaming | Server-sent events | `Last-Event-ID` resume |
| Tests | pytest, pytest-asyncio, httpx, Hypothesis | Property tests required |
| Quality | ruff (lint and format), mypy | |

## Document and AI processing (Phase 2+)
PaddleOCR (CPU), Docling, PyMuPDF, OpenCV, python-docx, openpyxl, stdlib `csv` and `email`. Models are reached through one OpenAI-compatible provider interface configured by `VERITAS_LLM_*` env vars (hosted API or a local Qwen2.5-VL or Qwen2.5-Instruct server). Never hardcode a model name, endpoint or GPU. Object storage is any S3 API through boto3. Docker Compose runs SeaweedFS (`chrislusf/seaweedfs`), because MinIO's community images were discontinued in 2025-2026. Use the single `opencv-contrib-python` build that PaddleX requires; never add a second OpenCV distribution, because both install into the same `cv2` package. Install with `uv sync --all-extras`: a plain `uv add` or `uv sync` removes the `ocr` and `layout` extras. Later phases add LangGraph, BGE embeddings and reranker, Qdrant and Neo4j.

## Cross-document comparison (Phase 3+)
Deterministic rules in plain Python. Party names are matched with `rapidfuzz` (token-sort ratio). It is added because it is a fast, symmetric, well-tested fuzzy matcher, and the stdlib `difflib` ratio isn't symmetric.

## Evidence graph (Phase 4+)
Neo4j 5.26 LTS community (Compose service `neo4j`) with the official async `neo4j` Python driver. Build Cypher only from the allowlisted labels and relationship types, and pass every value as a parameter. Postgres stays the source of truth; Neo4j is fed by the `outbox`, and the API falls back to Postgres. Scheduling uses Celery beat embedded in the worker (`-B`), not a separate service. The frontend draws graphs with `@xyflow/react` (React Flow) and `@dagrejs/dagre`, added for a deterministic hierarchical layout that React Flow doesn't provide.

## Frontend
React 18, TypeScript (strict), Vite, Tailwind CSS, shadcn/ui-style components (Radix primitives), TanStack Query, React Router, Zustand, Recharts, React Flow (graph), PDF.js (viewer). Tests use Vitest, Testing Library, msw (UI state tests only) and Playwright (end to end). The API types are generated from `backend/openapi.json` with openapi-typescript.

## Infrastructure
Docker and Docker Compose, Nginx as the reverse proxy and static host. Services: nginx (serves the frontend), backend, migrate (one-shot), postgres, redis, objectstore (SeaweedFS S3), celery-worker (separate image target with PaddleOCR and Docling). Later phases add qdrant and neo4j.

## Local development (Windows and Linux)
- The backend venv uses `uv` with Python 3.12: `uv venv --python 3.12 backend/.venv`.
- Workspace paths can contain spaces. Always quote paths in scripts.
