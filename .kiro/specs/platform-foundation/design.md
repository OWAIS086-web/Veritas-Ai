# Design: Platform Foundation

## Overview
This spec covers a FastAPI application factory (`app.main:create_app`), a Celery app (`app.workers.celery_app`), the SQLAlchemy async engine, and the React SPA served by Nginx. See `docs/architecture.md` for the system diagram.

## Components

### Backend
| Component | File | Responsibility |
|---|---|---|
| Settings | `app/core/config.py` | `Settings(BaseSettings)` with the `VERITAS_` prefix. `get_settings()` is cached. Validators enforce Req 1.2 and 1.3. |
| Logging | `app/core/logging.py` | stdlib logging with a JSON formatter. `request_id` is held in a `contextvar`. |
| Errors | `app/core/errors.py` | Domain exceptions plus handlers that produce problem+json. |
| Middleware | `app/core/middleware.py` | Request-id middleware and access logging. |
| Database | `app/core/db.py` | Async engine and `async_sessionmaker`. `get_session` dependency. `tenant_session(org_id)` runs `SET LOCAL app.current_org`. |
| Redis | `app/core/redis.py` | A shared `redis.asyncio.Redis` client. |
| Health | `app/api/v1/system.py` → `app/services/system/health.py` | `SELECT 1` and `PING`, each with a 2 s timeout. |
| Jobs | `app/models/job.py`, `app/services/jobs/service.py`, `app/api/v1/jobs.py` | `Job` and `JobEvent` models, `create_job`, `transition`, `list_events_after`, and the SSE generator. |
| Celery | `app/workers/celery_app.py`, `app/workers/system_tasks.py` | Broker and result backend from settings. `system.ping` task. `acks_late=True`, `task_reject_on_worker_lost=True`. |
| Stats | `app/services/stats/overview.py`, `app/api/v1/stats.py` | Aggregate counts per organization. |

### Data model (migration 0001)
- `organizations(id uuid pk, name, slug unique, retention_days int null, created_at, updated_at)`
- `users(id uuid pk, email citext unique, password_hash, full_name, is_active, created_at)`
- `roles(id smallint pk, key unique, name)`, seeded with `org_admin, investigation_manager, investigator, reviewer, read_only_analyst`
- `organization_members(id, organization_id fk, user_id fk, role_id fk, created_at, unique(organization_id,user_id))`, with RLS
- `refresh_tokens(id, organization_id, user_id, family_id, token_hash unique, expires_at, revoked_at, replaced_by_id, created_at)`, with RLS
- `audit_logs(id bigserial, organization_id null, actor_user_id null, action, resource_type, resource_id, ip, user_agent, metadata jsonb, created_at)`. RLS allows reading only the caller's org rows. INSERT and SELECT only for `veritas_app`.
- `jobs(id uuid, organization_id, kind, status, progress int, attempts, max_attempts, error, payload jsonb, result jsonb, created_by, created_at, updated_at)`, with RLS
- `job_events(id bigserial, job_id fk, organization_id, seq int, type, data jsonb, created_at, unique(job_id, seq))`, with RLS

#### RLS policy pattern
```sql
ALTER TABLE t ENABLE ROW LEVEL SECURITY;
CREATE POLICY t_tenant ON t
  USING (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid);
```
RLS is not `FORCE`d, so the owner-owned SECURITY DEFINER auth functions can read across tenants. The app role is never the owner, so the policies always apply to it. `organizations` uses the same policy on `id`.
Pre-auth lookups (login by email, refresh token lookup) need to read across organizations. They go through `SECURITY DEFINER` SQL functions owned by the owner role that return only the minimal columns:
- `auth_lookup_user(email)` returns `user_id, password_hash, is_active`.
- `auth_memberships(user_id)` returns `organization_id, role_key`.
- `auth_find_refresh(token_hash)` returns the token row.

`users` and `roles` are global tables. `users` is readable by `veritas_app`, but the API only returns user rows that are joined through a membership in the caller's org.

The roles `veritas_app` and `veritas_readonly` are created by `infrastructure/docker/postgres/init/01-roles.sh` from env passwords. Migrations grant privileges.

### API
| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/system/health` | Public |
| GET | `/api/v1/jobs/{job_id}` | `jobs:read` |
| GET | `/api/v1/jobs/{job_id}/events` | SSE (`text/event-stream`). Auth by `Authorization` header or `access_token` query param (EventSource can't set headers). |
| POST | `/api/v1/system/ping-job` | `system:ping`. Creates a real ping job for verifying the pipeline. |
| GET | `/api/v1/stats/overview` | `stats:read` |

### Frontend
- `src/app/router.tsx` holds the routes. `src/layouts/AppShell.tsx` has the sidebar and top bar.
- `src/services/api.ts` is a fetch wrapper. It attaches the bearer token, retries once after a refresh on 401, and parses problem+json into `ApiError`.
- `src/stores/auth.ts` is the Zustand store for tokens. The access token is kept in memory and the refresh token in `localStorage`. (Trade-off: an httpOnly cookie would be safer against XSS, but the SPA and API share an origin behind Nginx, so this is a candidate hardening in the security phase.)
- `src/components/ui/*` are primitives styled with the design tokens.
- `src/components/PhasePending.tsx` is the explicit pending state.

### Infrastructure
- `infrastructure/docker/backend.Dockerfile` is a multi-stage build on python:3.12-slim using uv, run as a non-root user.
- `infrastructure/docker/frontend.Dockerfile` builds with node:22 and serves from nginx:1.27-alpine, using `infrastructure/nginx/nginx.conf` (static files plus `/api` proxy, SSE buffering off).
- `docker-compose.yml` defines postgres:16-alpine and redis:7-alpine (with health checks), migrate, backend, celery-worker and nginx (port 8080).

## Data flow: job
Client POST → service inserts `jobs` (queued) and event seq 1 → commit → `task.delay(job_id)` → worker opens a tenant session, transitions to running (event), does the work, transitions to succeeded (event). The SSE endpoint polls `job_events` every 500 ms for seq > last, and closes after a terminal event.

## Failure handling
| Failure | Behavior |
|---|---|
| DB down at startup | Health returns 503. Requests return problem 503. |
| Redis down | Health returns 503. Login rate limiting fails closed (503) so limits can't be bypassed. |
| Worker crash mid-task | `acks_late` re-delivers the task. The task checks the job status and skips work if the job is already terminal (idempotent). |
| Retries exhausted | Job is `failed` with an `error` message and a `failed` event. |
| SSE client disconnect | The generator stops. Reconnect resumes from `Last-Event-ID`. |

## Testing
- Unit: settings validation, error handlers, the job state machine.
- Integration (real Postgres and Redis): health, migration cycle, RLS direct-SQL isolation, job lifecycle, SSE resume, and the stats endpoint returning zeros then counts.
- Property: job event sequence numbers stay strictly increasing under arbitrary transition sequences.
