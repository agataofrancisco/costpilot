"""Configuração do CostPilot, lida de variáveis de ambiente com prefixo COSTPILOT_."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> raiz do projecto
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COSTPILOT_", extra="ignore")

    database_url: str = f"sqlite:///{(REPO_ROOT / 'data' / 'costpilot.db').as_posix()}"
    redis_url: str | None = None
    config_dir: Path = REPO_ROOT / "config"

    admin_token: SecretStr | None = None
    allow_policy_override: bool = False

    provider_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    reservation_ttl_seconds: int = Field(default=120, gt=0, le=3600)
    cache_ttl_seconds: int = Field(default=3600, gt=0)
    default_max_output_tokens: int = Field(default=512, ge=1, le=8192)
    probe_on_startup: bool = True

    mock_enabled: bool = True
    mock_seed: int = 1

    openai_base_url: str | None = None
    openai_api_key: SecretStr | None = None
    modelmesh_base_url: str | None = None
    modelmesh_virtual_key: SecretStr | None = None

    @model_validator(mode="after")
    def _reservation_outlives_provider_timeout(self) -> Settings:
        # Reserva que expira antes da resposta do provider deixa o orçamento sobre-comprometido.
        if self.reservation_ttl_seconds < self.provider_timeout_seconds + 5:
            raise ValueError(
                "reservation_ttl_seconds tem de ser pelo menos provider_timeout_seconds + 5"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
