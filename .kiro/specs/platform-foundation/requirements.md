# Requirements: Platform Foundation

## Introduction
The foundation every VERITAS module builds on: backend and frontend skeletons, configuration, logging, error format, database and migrations, Redis and Celery job plumbing, the overview statistics endpoint, the design system and the Docker Compose environment.

## Requirement 1: Configuration
**User story:** As an operator, I want all settings to come from environment variables so the same build runs in development and production without code changes.

Acceptance criteria:
1. WHEN the backend starts THE SYSTEM SHALL load settings from environment variables prefixed `VERITAS_` (and from `.env` in development).
2. WHEN a required setting (`VERITAS_DATABASE_URL`, `VERITAS_JWT_SECRET`, `VERITAS_REDIS_URL`) is missing THE SYSTEM SHALL refuse to start and name the missing setting.
3. WHEN `VERITAS_ENV=production` and the JWT secret is shorter than 32 characters or starts with `CHANGE_ME` THE SYSTEM SHALL refuse to start.
4. THE SYSTEM SHALL NOT contain secrets in source control. `.env.example` holds only placeholders.

## Requirement 2: Health and observability
**User story:** As an operator, I want health checks and structured logs so I can see whether the platform works.

Acceptance criteria:
1. WHEN `GET /api/v1/system/health` is called THE SYSTEM SHALL return 200 with `{status, components:{database, redis}}`, where each component is `ok` or `error`.
2. WHEN any component is failing THE SYSTEM SHALL return 503 with the same body shape.
3. THE SYSTEM SHALL write logs as JSON lines that include a `request_id`. The id comes from the `X-Request-ID` header or is generated, and is echoed in the response header.
4. THE SYSTEM SHALL NOT log passwords, tokens or secrets.

## Requirement 3: Error format
Acceptance criteria:
1. WHEN any request fails THE SYSTEM SHALL return `application/problem+json` with `type, title, status, detail, instance` and no stack trace.
2. WHEN request validation fails THE SYSTEM SHALL return 422 with an `errors` array of `{loc, msg}` entries.

## Requirement 4: Database and migrations
Acceptance criteria:
1. THE SYSTEM SHALL manage the schema only through Alembic migrations, run by the owner role.
2. WHEN `alembic upgrade head`, then `alembic downgrade base`, then `alembic upgrade head` run on an empty database THE SYSTEM SHALL complete all three without errors.
3. THE SYSTEM SHALL connect the API and workers as the non-owner role `veritas_app`, which has no `BYPASSRLS`.
4. WHEN models and migrations diverge THE SYSTEM SHALL make `alembic check` fail.

## Requirement 5: Background jobs
**User story:** As a user, I want long-running work to run in the background with visible progress that survives a page refresh.

Acceptance criteria:
1. WHEN a job is submitted THE SYSTEM SHALL persist a `jobs` row with status `queued` before enqueueing the Celery task.
2. WHILE the task runs THE SYSTEM SHALL move the job through `running` → `succeeded` | `failed` and persist each transition as a job event with a monotonically increasing sequence number.
3. WHEN a task raises a retryable error THE SYSTEM SHALL retry it at most `max_attempts` times with exponential backoff, then mark the job `failed` with the error message.
4. WHEN a client opens `GET /api/v1/jobs/{id}/events` with `Last-Event-ID: n` THE SYSTEM SHALL stream only the events with sequence > n, then follow live events until the job is terminal.
5. WHEN a job belongs to another organization THE SYSTEM SHALL return 404.

## Requirement 6: Overview statistics
Acceptance criteria:
1. WHEN `GET /api/v1/stats/overview` is called THE SYSTEM SHALL compute every value from database queries scoped to the caller's organization.
2. WHEN the organization has no data THE SYSTEM SHALL return zeros or empty lists, never sample numbers.
3. WHEN metrics belong to modules not built yet THE SYSTEM SHALL return them as `null` with `available: false`, and the UI SHALL show "Available in a later phase".

## Requirement 7: Frontend foundation
Acceptance criteria:
1. THE SYSTEM SHALL provide an app shell with the 11 navigation sections in the order defined in `ui-design.md`.
2. WHEN a section's backend is not built THE SYSTEM SHALL render an explicit "Available in a later phase" state and SHALL NOT render sample data.
3. THE SYSTEM SHALL use typed API calls generated from `backend/openapi.json`.
4. WHEN any API call fails THE SYSTEM SHALL show the problem `title`/`detail` and offer a retry action.

## Requirement 8: Containerized environment
Acceptance criteria:
1. WHEN `docker compose up -d --build` runs on a clean clone with `.env` copied from `.env.example` THE SYSTEM SHALL start postgres, redis, migrate (one-shot), backend, celery-worker and nginx (which serves the frontend), and they SHALL become healthy.
2. WHEN the smoke script runs against `http://localhost:8080` THE SYSTEM SHALL pass health, register, login and `/auth/me`.
3. THE SYSTEM SHALL persist Postgres and Redis data in named volumes.
