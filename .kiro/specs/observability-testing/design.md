# Design: Observability and Testing

## Components
- `app/core/logging.py` has the JSON formatter and context variables (request id, job id, org id) bound by the middleware and the task prerun signals.
- `app/services/system/{health,metrics,models}.py`.
- `backend/scripts/benchmark.py` uses `time.perf_counter` around the stages (the values are also persisted in `document_stages.metrics`) and `psutil` for RSS (justification: cross-platform process memory).
- `scripts/quality-gate.{ps1,sh}`, `scripts/demo-reset.{ps1,sh}` and `scripts/smoke.{ps1,sh}`.

## Test layout
```
backend/tests/
  unit/          pure logic
  property/      Hypothesis
  integration/   real Postgres and Redis (Docker); fixtures create a fresh DB per session and transactions per test
  security/      tenant isolation, uploads, injection
  fixtures/      llm replay, malicious files
frontend/src/**/*.test.tsx   Vitest
frontend/tests/e2e/*.spec.ts Playwright
```

## Integration database strategy
The session fixture creates a database `veritas_test_<random>` as the owner, runs `alembic upgrade head`, connects the app as `veritas_app`, and drops the database at the end of the session. Tests clean up the rows they create. The owner connection comes from the migration settings (`VERITAS_MIGRATION_DATABASE_URL`, the same as the `migrate` service). If it is not set, the integration suite is skipped with an explicit reason, and the quality gate fails, so a missing database can't silently pass CI.

## Failure handling
Benchmarks record failures as data points, not as script crashes.
