# Deployment

## Requirements
- Docker Desktop (Windows, macOS) or Docker Engine 24+ with the Compose v2 plugin (Linux).
- About 2 GB of free RAM for the Phase 1 stack.
- Ports 8080 (web), and 5432 and 6379 bound to 127.0.0.1 in development only.

## Services
| Service | Image | Purpose |
|---|---|---|
| postgres | postgres:16-alpine | Source of truth. `infrastructure/docker/postgres/init/01-roles.sh` creates the non-owner `veritas_app` and the `veritas_readonly` roles on first start. |
| redis | redis:7-alpine | Rate limiting and the Celery broker and result backend |
| migrate | veritas-backend | One-shot `alembic upgrade head` as the owner role. Backend and worker wait for it to complete. |
| backend | veritas-backend | FastAPI on :8000 (internal only) |
| celery-worker | veritas-backend | Background jobs |
| nginx | veritas-frontend | Serves the SPA, proxies `/api`, sets security headers. Published on :8080. |

## Windows (PowerShell)
```powershell
Copy-Item .env.example .env
# Generate secrets and paste them over every CHANGE_ME value in .env:
python -c "import secrets; print(secrets.token_urlsafe(48))"
docker compose up -d --build
docker compose ps                       # wait until backend, celery-worker and nginx are healthy
pwsh -File scripts/smoke.ps1            # end-to-end check through Nginx
```

## Linux / macOS
```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # paste over CHANGE_ME values
docker compose up -d --build
docker compose ps
scripts/smoke.sh
```

Open http://localhost:8080. The API documentation is at http://localhost:8080/api/docs.

Use URL-safe characters (letters, digits, `-`, `_`) for database passwords, because they are embedded in connection URLs.

## Production
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```
The override removes the published Postgres and Redis ports, sets `VERITAS_ENV=production`, and uses `restart: always`. In production the backend refuses to start with a placeholder or short JWT secret. Terminate TLS in front of port 8080 (load balancer or reverse proxy) and set HSTS there.

## Document processing services (Phase 2)
- **objectstore**: SeaweedFS with its S3 API (MinIO's community images were discontinued in 2025-2026). The S3 identity is generated at start from `VERITAS_STORAGE_ACCESS_KEY` and `VERITAS_STORAGE_SECRET_KEY`. Port 8333 is mapped to `127.0.0.1:9000` for development only.
- **celery-worker**: built from the `worker` target, with PaddleOCR, Docling and CPU-only torch (about 4.5 GB). On start it runs `scripts/warm_models.py`. The first run downloads the models into the `models` volume, which took 155 s for Docling here. Later starts load from the cache in seconds. The health check allows 10 minutes for that first start.
- The worker's concurrency defaults to 1 (`VERITAS_WORKER_CONCURRENCY`). Each process holds its own OCR and layout models in memory.

## Evidence graph (Phase 4)
- **neo4j** (`neo4j:5.26-community`, LTS) holds the derived graph in the `graphdata` volume. The password comes from `VERITAS_NEO4J_PASSWORD` in `.env`. The heap is capped at 512 MB and the page cache at 256 MB. Bolt is published on `127.0.0.1:7687` for development only.
- No other service depends on it. If it is down, the API serves graphs from Postgres (`X-Graph-Source: postgres`), `/system/health` shows `graph.status = error`, and the outbox keeps the changes until it is back.
- The worker runs Celery beat embedded (`celery worker -B`). It drains the graph outbox every 15 s and reconciles every 10 minutes, so no extra scheduler container is needed. With more than one worker, run beat in only one of them.
- `VERITAS_NEO4J_NAMESPACE` separates deployments or test runs that share one Neo4j. The integration tests use a random namespace.

## Document forensics (Phase 5)
- Forensics adds no service. It runs in the existing worker as the last processing stage, using PyMuPDF and OpenCV, which are already installed.
- Migration 0005 is applied by the `migrate` service on `docker compose up`.
- Settings (`.env`, passed through by Compose):
  - `VERITAS_FORENSICS_ENABLED` (true)
  - `VERITAS_FORENSICS_DPI` (110)
  - `VERITAS_FORENSICS_MAX_PAGES` (20)
  - `VERITAS_FORENSICS_NOISE_K` (6.0)
  - `VERITAS_FORENSICS_VERSION_SSIM` (0.6)
  - `VERITAS_FORENSICS_STAMP_THRESHOLD` (0.004)
- The thresholds were calibrated on `sample-data/forensics` (see `docs/ai-pipeline.md`). Change them only with a recalibration.
- Measured on the Docker stack (2026-11-23, CPU worker), from `document_stages` timestamps: 38 digital PDFs took 163 ms on average and 230 ms at most. One scanned PDF over 1 MB took 1.7 s.
- To regenerate the fixtures: `uv run python scripts/generate_forensics_samples.py`, from `backend/`. The output is deterministic, and the hashes are recorded in `manifest.json`.
- The smoke test checks that both shipment documents get a forensic run with the mandatory limitation.

## Autonomous investigation (Phase 6)
- No new service. The Celery task `investigations.run` runs the LangGraph workflow in the existing worker. LangGraph (`langgraph>=1.2,<1.3`) was added to the backend dependencies.
- Migration 0006 adds the investigation tables, including LangGraph's checkpoints.
- The agents call the configured model provider (`VERITAS_LLM_*`). Without one, the planner fails and the investigation is marked `failed` with that reason. Nothing is invented in its place.
- Budgets come from `VERITAS_INVESTIGATION_*`: max iterations 24, max tool calls 80, timeout 900 s, max tokens 120,000, and 3,000 page characters per prompt. The Celery time limit is the timeout plus 120 s.
- Measured with local Ollama `qwen2.5:7b-instruct` on 2026-11-23, for the invoice and customs declaration pair (5 findings), over 6 runs: 4 through the live pytest and 2 in the browser on the Docker stack. Reaching review took 24.4–46 s, with 7–10 iterations, 27–33 tool calls and 14,986–22,539 provider-reported tokens. The report step wasn't timed separately.
- The live browser test needs the model: `VERITAS_E2E_LIVE_MODEL=1 npx playwright test tests/e2e/agents.spec.ts`.

## Reports and the evidence explorer (Phase 7)
- No new service and no new environment variable. The Celery task `reports.generate` runs in the existing worker. Report files go to the existing object store under the organization's prefix, and downloads use the same 60 s signed links (`VERITAS_SIGNED_URL_SECONDS`).
- PDF output uses PyMuPDF, which is already installed, so ReportLab and its system packages aren't needed. DOCX and XLSX use python-docx and openpyxl, both already dependencies.
- Migration 0007 adds `reports`, `findings.assignee_user_id` and `evidence_requests.finding_id`.
- The smoke test now generates a PDF report and checks that the signed download matches its recorded SHA-256.
- The demo case's PDF report was 169 KB on the stack.
- **Test load:** run the quality gate and the Playwright suite while the machine is otherwise idle. A Docker image build running at the same time made unrelated frontend tests time out. Right after a backend restart, the first registrations of four parallel Playwright workers can also take more than 5 s. Both cases are recorded in the progress document.
- To check an outage on the running stack: `pwsh -File scripts/graph-outage-check.ps1`. It stops and starts the `neo4j` container.
- Data volumes now include `veritas_graphdata`.

## Document Comparison Lab (original versus test)
- No new service and no new dependency. The Celery tasks `doccompare.run` (time limit 30 min, waits up to 30 min for both documents to be processed, retrying every 10 s) and `doccompare.export` run in the existing worker. Migration 0008 adds the four tables.
- Settings (`.env`, passed through by Compose; see `.env.example`):
  - `VERITAS_COMPARISON_DPI` (144), `VERITAS_COMPARISON_MAX_PAGES` (20), `VERITAS_COMPARISON_WORK_WIDTH` (1000), `VERITAS_COMPARISON_SSIM_THRESHOLD` (0.6)
  - `VERITAS_COMPARISON_VLM_ENABLED` (true), `VERITAS_COMPARISON_VLM_MAX_REGIONS` (8), `VERITAS_COMPARISON_VLM_MAX_PAGES` (3)
- **Vision model (Qwen2.5-VL 7B through Ollama):**
  1. `ollama pull qwen2.5vl:7b` (about 6 GB; runs on CPU, faster with a GPU).
  2. In `.env`: `VERITAS_LLM_BASE_URL=http://host.docker.internal:11434/v1` and `VERITAS_VLM_MODEL=qwen2.5vl:7b`, with `VERITAS_LLM_TIMEOUT_SECONDS=180` for the first, cold call. For containers on Linux the same value works through `extra_hosts`. Leave `VERITAS_LLM_API_KEY` empty.
  3. `docker compose up -d backend celery-worker`, then open Forensics Lab → Comparison Lab: the badge shows "Vision model ready", or check `GET /api/v1/system/vlm-status`.
  4. Any OpenAI-compatible server (vLLM, LM Studio, a hosted API) works with the same two variables; the model name is never hardcoded. Without a reachable model, comparisons complete with text and pixel evidence and `vlm_status` says why.
- Measured on this machine (2026-11-23, Ollama on the host, CPU worker): a vision call took 2–11 s once the model was loaded (the first call after loading took about 20 s). Comparing the two-page altered invoice took 25.6 s for the vision step (4 calls, 9,750 tokens) on top of about 18 s of rasterizing, alignment and comparison. The rotated scan took 36 s without the model, most of it PaddleOCR.
- Sample files: `sample-data/comparison` (regenerate with `uv run python scripts/generate_comparison_samples.py` from `backend/`).

## Local model provider (Ollama)
- Set `VERITAS_LLM_BASE_URL=http://host.docker.internal:11434/v1` and `VERITAS_LLM_MODEL=qwen2.5:7b-instruct` in `.env`, then run `docker compose up -d backend celery-worker`. The worker has `extra_hosts: host.docker.internal:host-gateway`, so the same value works on Linux.
- Ollama needs no API key; leave `VERITAS_LLM_API_KEY` empty. Use local models only. Ollama's `-cloud` models send document text to a third party.
- Check it on the running stack: `pwsh -File scripts/live-llm-check.ps1` (the 7 shipment PDFs) or with `-Variants` (OCR and parser formats). Run the live tests with `VERITAS_LIVE_LLM_BASE_URL=http://127.0.0.1:11434/v1 VERITAS_LIVE_LLM_MODEL=qwen2.5:7b-instruct uv run pytest -m live`.

## Cross-document comparison (Phase 3)
- No new service. Comparison runs in the existing `celery-worker` (task `cases.compare`, and at the end of every processing job). Migration 0003 is applied by the `migrate` service on the next `docker compose up`.
- Optional settings: `VERITAS_AMOUNT_TOLERANCE` (default 0.005) and `VERITAS_NAME_SIMILARITY_THRESHOLD` (default 0.85). See `.env.example`.
- The smoke test now also checks the comparison: an invoice and a customs declaration must give one USD 20,000.00 finding with 2 evidence items.

## Local development without containers for the app
```powershell
docker compose up -d postgres redis objectstore
# --all-extras installs the ocr and layout extras; a plain `uv sync` or `uv add` removes them.
cd backend; uv sync --all-extras; uv run alembic upgrade head; uv run uvicorn app.main:app --reload
cd frontend; npm install; npm run dev          # http://localhost:5173, proxies /api to :8000
```
On Windows, use `127.0.0.1` rather than `localhost` in `.env` URLs. `localhost` resolves to IPv6 first, and Docker binds IPv4, which causes 2-second connection stalls.

## Quality gate and tests
```powershell
docker compose up -d postgres redis objectstore
pwsh -File scripts/quality-gate.ps1      # Linux: scripts/quality-gate.sh  (about 5 minutes: real OCR and Docling)
cd frontend; npx playwright install chromium; npx playwright test   # needs the full stack running
```

## Data and resets
- Data lives in the named volumes `veritas_pgdata`, `veritas_redisdata`, `veritas_objectdata` (originals and derived page images) and `veritas_models` (OCR and layout model cache). `docker compose down` keeps them.
- Deleting volumes (`docker compose down -v`) erases all data. Only do this deliberately.
