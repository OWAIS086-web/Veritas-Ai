# VERITAS AI backend. Build context: ./backend
#   target "api"    -> API and migrations (no OCR or layout models)
#   target "worker" -> Celery worker with PaddleOCR and Docling (CPU)
FROM python:3.12-slim AS base-build
ENV PIP_NO_CACHE_DIR=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
RUN pip install --no-cache-dir "uv>=0.5,<1"
WORKDIR /src
COPY pyproject.toml uv.lock ./

FROM base-build AS api-build
RUN uv sync --frozen --no-dev --no-install-project

FROM base-build AS worker-build
RUN uv sync --frozen --no-dev --no-install-project --extra ocr --extra layout

FROM python:3.12-slim AS runtime-base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH"
# libgl/libglib: the OpenCV build shared with PaddleX imports them; libgomp: Paddle and torch.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*
RUN groupadd --system veritas && useradd --system --gid veritas --home-dir /app --shell /usr/sbin/nologin veritas
WORKDIR /app

FROM runtime-base AS api
COPY --from=api-build /opt/venv /opt/venv
COPY --chown=veritas:veritas alembic.ini ./
COPY --chown=veritas:veritas app ./app
COPY --chown=veritas:veritas migrations ./migrations
COPY --chown=veritas:veritas scripts ./scripts
USER veritas
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime-base AS worker
# Model caches live in a volume; the directory is created here so the volume is owned by veritas.
ENV PADDLE_PDX_CACHE_HOME=/models/paddlex HF_HOME=/models/huggingface \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True OMP_NUM_THREADS=4
RUN mkdir -p /models && chown veritas:veritas /models
COPY --from=worker-build /opt/venv /opt/venv
COPY --chown=veritas:veritas alembic.ini ./
COPY --chown=veritas:veritas app ./app
COPY --chown=veritas:veritas migrations ./migrations
COPY --chown=veritas:veritas scripts ./scripts
USER veritas
CMD ["celery", "-A", "app.workers.celery_app", "worker", "--loglevel=INFO", "--concurrency=1"]
