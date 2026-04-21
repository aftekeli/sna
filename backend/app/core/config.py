from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENV_FILE = REPO_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(DEFAULT_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Turkiye Cinema KG-Infused RAG Backend"
    app_env: str = Field(default="development", alias="APP_ENV")
    app_debug: bool = Field(default=True, alias="APP_DEBUG")
    app_allowed_origins: str | None = Field(default=None, alias="APP_ALLOWED_ORIGINS")
    project_domain: str = "cinema"
    api_prefix: str = "/api/v1"
    runtime_storage_root: Path | None = Field(default=None, alias="RUNTIME_STORAGE_ROOT")

    groq_api_key: str | None = Field(default=None, alias="GROQ_API_KEY")
    groq_model: str = Field(default="openai/gpt-oss-120b", alias="GROQ_MODEL")
    groq_mode: str = Field(default="free", alias="GROQ_MODE")
    groq_check_before_each_action: bool = Field(
        default=True,
        alias="GROQ_CHECK_BEFORE_EACH_ACTION",
    )
    groq_allow_ollama_fallback: bool = Field(
        default=False,
        alias="GROQ_ALLOW_OLLAMA_FALLBACK",
    )
    groq_pause_until_next_day_on_limit: bool = Field(
        default=True,
        alias="GROQ_PAUSE_UNTIL_NEXT_DAY_ON_LIMIT",
    )
    groq_usage_timezone: str = Field(default="Europe/Istanbul", alias="GROQ_USAGE_TIMEZONE")
    groq_request_pacing_rpm: int = Field(default=12, alias="GROQ_REQUEST_PACING_RPM")
    groq_default_retry_after_seconds: int = Field(
        default=60,
        alias="GROQ_DEFAULT_RETRY_AFTER_SECONDS",
    )
    groq_consecutive_429_before_cooldown: int = Field(
        default=3,
        alias="GROQ_CONSECUTIVE_429_BEFORE_COOLDOWN",
    )
    groq_cooldown_seconds: int = Field(default=300, alias="GROQ_COOLDOWN_SECONDS")
    groq_daily_cooldown_limit: int = Field(default=3, alias="GROQ_DAILY_COOLDOWN_LIMIT")
    groq_daily_stop_threshold_requests: int = Field(
        default=50,
        alias="GROQ_DAILY_STOP_THRESHOLD_REQUESTS",
    )
    groq_request_reserve: int | None = Field(default=None, alias="GROQ_REQUEST_RESERVE")
    groq_token_reserve: int | None = Field(default=None, alias="GROQ_TOKEN_RESERVE")
    groq_quota_cache_ttl_seconds: int = Field(
        default=60,
        alias="GROQ_QUOTA_CACHE_TTL_SECONDS",
    )
    groq_request_reserve_floor: int = Field(
        default=10,
        alias="GROQ_REQUEST_RESERVE_FLOOR",
    )
    groq_request_reserve_percent: float = Field(
        default=0.02,
        alias="GROQ_REQUEST_RESERVE_PERCENT",
    )
    groq_token_reserve_floor: int = Field(
        default=1000,
        alias="GROQ_TOKEN_RESERVE_FLOOR",
    )
    groq_token_reserve_percent: float = Field(
        default=0.10,
        alias="GROQ_TOKEN_RESERVE_PERCENT",
    )

    neo4j_uri: str | None = Field(default=None, alias="NEO4J_URI")
    neo4j_username: str | None = Field(default=None, alias="NEO4J_USERNAME")
    neo4j_password: str | None = Field(default=None, alias="NEO4J_PASSWORD")
    neo4j_database: str = Field(default="neo4j", alias="NEO4J_DATABASE")

    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="qwen2.5-coder:14b", alias="OLLAMA_MODEL")

    @model_validator(mode="before")
    @classmethod
    def normalize_string_inputs(cls, data):
        if not isinstance(data, dict):
            return data
        normalized: dict[object, object] = {}
        for key, value in data.items():
            normalized[key] = value.strip() if isinstance(value, str) else value
        return normalized

    @property
    def env_file(self) -> Path:
        return DEFAULT_ENV_FILE

    @property
    def artifacts_dir(self) -> Path:
        return REPO_ROOT / "artifacts"

    @property
    def allowed_origins(self) -> list[str]:
        if self.app_allowed_origins:
            origins = [origin.strip() for origin in self.app_allowed_origins.split(",")]
            return [origin for origin in origins if origin]
        return [
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3001",
            "http://127.0.0.1:3002",
            "http://127.0.0.1:3003",
            "http://localhost:3000",
            "http://localhost:3001",
            "http://localhost:3002",
            "http://localhost:3003",
        ]

    @property
    def runtime_root_dir(self) -> Path:
        if self.runtime_storage_root is not None:
            return self.runtime_storage_root
        if self.app_env.casefold() == "production":
            return Path("/tmp/sna-runtime")
        return self.artifacts_dir / "runtime"

    @property
    def groq_runtime_dir(self) -> Path:
        return self.runtime_root_dir / "groq"

    @property
    def chat_runtime_dir(self) -> Path:
        return self.runtime_root_dir / "chat"

    @property
    def phase3_dir(self) -> Path:
        return self.artifacts_dir / "phase-3"

    @property
    def phase4_dir(self) -> Path:
        return self.artifacts_dir / "phase-4"

    @property
    def phase5_dir(self) -> Path:
        return self.artifacts_dir / "phase-5"

    @property
    def phase6_dir(self) -> Path:
        return self.artifacts_dir / "phase-6"

    @property
    def phase7_dir(self) -> Path:
        return self.artifacts_dir / "phase-7"

    @property
    def phase3_entities_path(self) -> Path:
        return self.phase3_dir / "neo4j_import" / "entities.csv"

    @property
    def phase3_relationships_path(self) -> Path:
        return self.phase3_dir / "neo4j_import" / "relationships.csv"

    @property
    def phase4_dataset_path(self) -> Path:
        return self.phase4_dir / "turkiye_cinema_multihop_qa.json"

    @property
    def phase5_retrieval_db_path(self) -> Path:
        return self.phase5_dir / "retrieval" / "baseline_corpus.sqlite3"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
