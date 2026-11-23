# Requirements: Observability, Performance and Testing

## Requirement 1: Logging and errors
1. All backend and worker logs SHALL be JSON with `timestamp, level, event, request_id | job_id | investigation_id, organization_id`.
2. Unhandled exceptions SHALL be logged with a traceback server-side, and SHALL return a problem+json 500 with only a correlation id to the client.

## Requirement 2: Health and metrics
1. `GET /system/health` SHALL report the database, Redis, storage, worker liveness (Celery ping), and later Neo4j and Qdrant.
2. `GET /system/metrics` (admin only) SHALL report queue depths, stage success and failure counts, and mean stage durations computed from `document_stages`.
3. `GET /system/models` SHALL list the configured providers and models, with reachability, and never the API keys.

## Requirement 3: Benchmarks
1. `backend/scripts/benchmark.py` SHALL process the synthetic dataset N times and report the mean and p95 for OCR time, extraction time, time per page, investigation time, peak worker RSS memory, model inference time, and the success and failure rates.
2. The results SHALL be written to `docs/benchmarks.md` with the machine description and date. No other performance claims are made.

## Requirement 4: Test suites
1. The unit, property, integration, security and end-to-end suites SHALL run through `scripts/quality-gate.ps1` and `.sh`.
2. The end-to-end shipment scenario SHALL cover upload → processing → extraction values → comparison → the 20,000 discrepancy → evidence opened at the cited pages → graph → investigation events → report citations verified.
3. Critical tests SHALL NOT be skipped. A skip SHALL require a documented environment reason and a Blocked entry in the progress doc.

## Requirement 5: Demo reliability
1. `scripts/demo-reset.ps1` and `.sh` SHALL reset the demo organization and seed it from `sample-data/shipment-case` through the public API, so that a clean environment reproduces the demo.
