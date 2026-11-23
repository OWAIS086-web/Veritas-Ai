# Tasks: Platform Foundation

A task is ticked only after its tests pass (see `docs/implementation-progress.md` for the evidence).

- [x] 1. Backend skeleton: settings, logging, errors, health
  - `app/core/{config,logging,errors,middleware}.py`, `app/main.py`, `app/api/v1/system.py`
  - Done when: `pytest tests/unit/test_config.py tests/unit/test_errors.py` pass. The health integration test returns 200 with database and redis `ok`. A missing `VERITAS_JWT_SECRET` raises at startup.
  - _Requirements: 1.1–1.4, 2.1–2.4, 3.1–3.2_

- [x] 2. Database engine, roles and migration 0001
  - `app/core/db.py`, `app/models/*`, `migrations/versions/0001_foundation.py`, `infrastructure/docker/postgres/init/01-roles.sh`
  - Done when: the upgrade → downgrade → upgrade cycle passes on a clean database. `alembic check` reports no drift. A direct-SQL test as `veritas_app` with `app.current_org=A` sees zero rows of org B.
  - _Requirements: 4.1–4.4_

- [x] 3. Jobs, Celery and SSE
  - `app/models/job.py`, `app/services/jobs/*`, `app/workers/*`, `app/api/v1/jobs.py`
  - Done when: a ping job reaches `succeeded` through a real worker. A forced-failure task ends `failed` after `max_attempts`. SSE with `Last-Event-ID` returns only later events. Another org's job returns 404. The Hypothesis sequence property passes.
  - _Requirements: 5.1–5.5_

- [x] 4. Overview stats endpoint
  - Done when: an empty org returns zeros. After inserting members and jobs, the counts match. Pending metrics are `available:false`.
  - _Requirements: 6.1–6.3_

- [x] 5. Frontend scaffold and design system
  - Vite, React, TS strict, Tailwind tokens, UI primitives, AppShell with 11 nav sections, PhasePending, API client, generated types
  - Done when: `npm run typecheck`, `npm run lint` and `npm run test` pass. A test asserts all 11 nav labels in order and that pending sections show the pending state.
  - _Requirements: 7.1–7.4_

- [x] 6. Docker Compose environment and smoke test
  - Dockerfiles, nginx.conf, docker-compose.yml, docker-compose.prod.yml, scripts/smoke.{ps1,sh}, docs/deployment.md
  - Done when: `docker compose up -d --build` reaches healthy and `scripts/smoke.ps1` passes.
  - _Requirements: 8.1–8.3_
