---
inclusion: fileMatch
fileMatchPattern: ["**/*.py", "**/*.ts", "**/*.tsx"]
---

# Coding standards

## Python
- Python 3.12. Full type hints. `mypy` must pass for `backend/app`.
- `ruff format` and `ruff check` must be clean. Line length is 100.
- Use `async def` for I/O paths. Never block the event loop. Wrap CPU-heavy work in Celery tasks.
- Raise domain errors from `app.core.errors` (`NotFoundError`, `ConflictError`, `PermissionDeniedError`, `ValidationFailedError`). The global handler turns them into RFC 7807 problem+json. Don't raise `HTTPException` from services.
- Log with `structlog`-style structured fields (`logger.info("event_name", key=value)`). Never log secrets, tokens, passwords or document contents.
- Money is `Decimal`, never `float`. Timestamps are timezone-aware UTC.
- Keep files focused. If a module exceeds about 400 lines, split it.
- Every new public service function has a test.

## TypeScript / React
- `strict: true`. No `any` unless it is justified in a comment.
- API calls go through `src/services/api.ts`. Server state lives in TanStack Query, client UI state in Zustand.
- Components live in `components/` (generic) or `features/<feature>/` (feature-specific). Pages are thin.
- Every async view handles its loading, empty and error states.
- Use design tokens through Tailwind classes. No raw hex values in components.

## General
- No dead code, no commented-out code, and no TODOs without a tracking task in a spec.
- Commit messages: `<area>: <imperative summary>`.
