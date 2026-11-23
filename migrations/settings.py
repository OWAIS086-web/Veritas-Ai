"""Settings used only by migrations (owner connection and role names for grants)."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]
_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class MigrationSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VERITAS_", env_file=(str(_REPO_ROOT / ".env"),), extra="ignore"
    )

    migration_database_url: str
    app_db_user: str = "veritas_app"
    ro_db_user: str = "veritas_readonly"

    @field_validator("app_db_user", "ro_db_user")
    @classmethod
    def _safe_identifier(cls, value: str) -> str:
        # Role names are interpolated into GRANT statements (identifiers cannot be bound),
        # so they are restricted to a strict identifier pattern.
        if not _IDENT.match(value):
            raise ValueError(f"unsafe role name: {value!r}")
        return value


@lru_cache
def get_migration_settings() -> MigrationSettings:
    return MigrationSettings()  # type: ignore[call-arg]
