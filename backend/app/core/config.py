"""Application settings, loaded only from environment variables (prefix VERITAS_)."""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VERITAS_",
        env_file=(str(_REPO_ROOT / ".env"),),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    # Required: no defaults, so a missing value stops startup.
    database_url: str
    redis_url: str
    jwt_secret: str = Field(repr=False)

    db_null_pool: bool = False
    db_pool_size: int = 10

    access_token_minutes: int = Field(default=15, ge=1, le=60)
    refresh_token_days: int = Field(default=7, ge=1, le=90)
    login_rate_limit_per_minute: int = Field(default=10, ge=1)
    # Per member and minute: upload requests (each may carry many files) and investigation starts.
    upload_rate_limit_per_minute: int = Field(default=30, ge=1)
    investigation_rate_limit_per_minute: int = Field(default=5, ge=1)
    # How often the worker's beat runs the retention purge (organizations.retention_days).
    retention_purge_interval_seconds: int = Field(default=3600, ge=60, le=604_800)
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    job_max_attempts: int = Field(default=3, ge=1, le=10)

    # Object storage (any S3 API; SeaweedFS in Compose). Originals are never overwritten.
    storage_endpoint: str = "127.0.0.1:9000"
    storage_region: str = "us-east-1"
    storage_access_key: str = Field(default="", repr=False)
    storage_secret_key: str = Field(default="", repr=False)
    storage_bucket: str = "veritas-documents"
    storage_secure: bool = False
    signed_url_seconds: int = Field(default=60, ge=10, le=900)

    # Upload limits (document-processing.md).
    max_upload_mb: int = Field(default=25, ge=1, le=500)
    zip_max_entries: int = Field(default=50, ge=1, le=1000)
    zip_max_total_mb: int = Field(default=200, ge=1, le=5000)
    zip_max_ratio: int = Field(default=100, ge=2, le=1000)
    max_pages: int = Field(default=200, ge=1, le=5000)

    # Pipeline.
    pipeline_version: str = "p2.1"
    stage_max_attempts: int = Field(default=3, ge=1, le=5)
    ocr_enabled: bool = True
    ocr_dpi: int = Field(default=200, ge=100, le=400)
    ocr_det_model: str = "PP-OCRv5_mobile_det"
    ocr_rec_model: str = "en_PP-OCRv5_mobile_rec"
    layout_enabled: bool = True
    layout_timeout_seconds: int = Field(default=120, ge=5, le=1800)

    # Cross-document comparison.
    amount_tolerance: Decimal = Field(default=Decimal("0.005"), ge=0, le=Decimal("0.5"))
    name_similarity_threshold: float = Field(default=0.85, ge=0.5, le=1.0)

    # Evidence graph (derived from Postgres; optional at runtime, the API falls back).
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = Field(default="", repr=False)
    neo4j_timeout_seconds: float = Field(default=5, ge=1, le=60)
    # Stored on every node and edge and filtered in every query, so several deployments
    # (or a test run) can share one Neo4j without seeing or deleting each other's graphs.
    neo4j_namespace: str = Field(default="default", pattern=r"^[a-z0-9_-]{1,40}$")
    outbox_max_attempts: int = Field(default=5, ge=1, le=20)
    # Names at or above this similarity merge into one entity; between the comparison
    # threshold and this value they stay separate and are flagged possible_duplicate.
    entity_merge_threshold: float = Field(default=0.95, ge=0.5, le=1.0)

    # Document forensics. Thresholds were calibrated on the generated fixtures and the
    # shipment samples (see docs/ai-pipeline.md).
    forensics_enabled: bool = True
    forensics_dpi: int = Field(default=110, ge=72, le=300)
    forensics_max_pages: int = Field(default=20, ge=1, le=500)
    forensics_noise_k: float = Field(default=6.0, ge=2.0, le=20.0)
    forensics_version_ssim: float = Field(default=0.6, ge=0.1, le=0.99)
    forensics_stamp_threshold: float = Field(default=0.004, ge=0.0005, le=0.5)

    # Original-versus-test document comparison. Pages are registered and compared at
    # `comparison_work_width` pixels; crops for the vision model and the annotated files come
    # from rasters at `comparison_dpi`.
    comparison_dpi: int = Field(default=144, ge=72, le=300)
    comparison_max_pages: int = Field(default=20, ge=1, le=200)
    comparison_work_width: int = Field(default=1000, ge=400, le=3000)
    comparison_ssim_threshold: float = Field(default=0.6, ge=0.1, le=0.99)
    # The vision model (VERITAS_VLM_MODEL, e.g. qwen2.5vl:7b) checks the strongest candidate
    # regions and scans pages for differences the deterministic steps missed. Its boxes are
    # used only when pixel evidence confirms them.
    comparison_vlm_enabled: bool = True
    comparison_vlm_max_regions: int = Field(default=8, ge=0, le=50)
    comparison_vlm_max_pages: int = Field(default=3, ge=0, le=50)

    # Autonomous investigation budgets (per investigation). Exceeding any of them stops the
    # run with status `budget_exhausted` and keeps the partial results.
    investigation_max_iterations: int = Field(default=24, ge=1, le=200)
    investigation_max_tool_calls: int = Field(default=80, ge=1, le=1000)
    investigation_timeout_seconds: int = Field(default=900, ge=10, le=7200)
    investigation_max_tokens: int = Field(default=120_000, ge=1000, le=5_000_000)
    # Characters of page text an agent may put into one prompt (inside <document_data>).
    investigation_max_page_chars: int = Field(default=3000, ge=200, le=20_000)

    # Model provider (OpenAI-compatible). Empty base URL means "no provider configured":
    # the deterministic rules extractor is used and recorded as such.
    llm_base_url: str = ""
    llm_api_key: str = Field(default="", repr=False)
    llm_model: str = ""
    vlm_model: str = ""
    llm_timeout_seconds: float = Field(default=60, ge=1, le=600)
    llm_fallback_models: str = ""

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("VERITAS_DATABASE_URL must use the postgresql+asyncpg:// scheme")
        return value

    @model_validator(mode="after")
    def _production_secret(self) -> Settings:
        weak = len(self.jwt_secret) < 32 or self.jwt_secret.startswith("CHANGE_ME")
        if self.env == "production" and weak:
            raise ValueError(
                "VERITAS_JWT_SECRET must be at least 32 characters and not a placeholder "
                "in production"
            )
        if len(self.jwt_secret) < 16:
            raise ValueError("VERITAS_JWT_SECRET must be at least 16 characters")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_model)

    @property
    def llm_models(self) -> list[str]:
        fallbacks = [m.strip() for m in self.llm_fallback_models.split(",") if m.strip()]
        return [self.llm_model, *fallbacks] if self.llm_model else fallbacks

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url


@lru_cache
def get_settings() -> Settings:
    return Settings()  # required values come from the environment
