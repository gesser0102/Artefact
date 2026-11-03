from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "EMPORIO_"
ENV_FILE = ".env"
ENV_FILE_ENCODING = "utf-8"
ENABLED_DEBUG_VALUES = frozenset({"1", "true", "yes", "on"})
GROQ_API_KEY_ALIASES = AliasChoices("GROQ_API_KEY", "EMPORIO_GROQ_API_KEY", "groq_api_key")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=ENV_FILE,
        env_file_encoding=ENV_FILE_ENCODING,
        extra="ignore",
    )

    data_dir: Path = Path("data")
    debug: bool = False
    groq_api_key: SecretStr | None = Field(default=None, validation_alias=GROQ_API_KEY_ALIASES)
    model: str = "openai/gpt-oss-120b"
    fallback_model: str | None = "openai/gpt-oss-20b"
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_timeout_seconds: float = 60.0
    max_completion_tokens: int = 1024
    reasoning_effort: str = "low"
    temperature: float = 0.3
    trace_dir: Path | None = None

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug_flag(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower() in ENABLED_DEBUG_VALUES
        return value

    @field_validator("groq_api_key", mode="before")
    @classmethod
    def ignore_blank_api_key(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value
