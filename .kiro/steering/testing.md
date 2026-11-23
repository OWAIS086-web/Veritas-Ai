---
inclusion: fileMatch
fileMatchPattern: ["**/tests/**", "**/*.test.*", "**/*.spec.*"]
---

# Testing standards and quality gates

## Layers
| Layer | Tooling | Runs against |
|---|---|---|
| Unit | pytest, Vitest | Pure functions and services with in-process fakes |
| Property | Hypothesis | Normalizers, hashing, token handling, tenant isolation, evidence integrity |
| Integration | pytest + httpx ASGI client | A **real PostgreSQL and Redis** (Docker); RLS is tested with the real `veritas_app` role |
| End to end | Playwright | The full Docker Compose stack through Nginx |

## Rules
- Never skip, `xfail` or weaken a critical test to get green. If a test needs an unavailable dependency (Docker, model credentials), it is skipped with an explicit reason, *and* the gap is recorded as Blocked in `docs/implementation-progress.md`.
- Tests that need a model provider use **recorded responses** (`tests/fixtures/llm/*.json`). Live provider tests are marked `@pytest.mark.live` and reported separately.
- Every bug fix comes with a regression test.
- Tenant isolation tests are mandatory for every new tenant-owned endpoint. They create two organizations and assert that the other organization's ids give 404.
- Use Hypothesis for invariants (round trips, idempotence, monotonicity) on every normalizer.

## Quality gate (`scripts/quality-gate.ps1` / `.sh`)
1. `ruff format --check`, `ruff check`, `mypy app`
2. `pytest` (unit, property and integration)
3. The OpenAPI contract check (`scripts/check_openapi.py`)
4. Frontend `typecheck`, `lint` and `test`

A spec task checkbox is ticked only after the gate passes for that task.
