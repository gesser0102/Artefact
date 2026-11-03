from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PREFIX = "EMPORIO_"
ENV_FILE = PROJECT_ROOT / ".env"
ENV_FILE_ENCODING = "utf-8"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
ENABLED_DEBUG_VALUES = frozenset({"1", "true", "yes", "on"})
GROQ_API_KEY_FIELD = "groq_api_key"
GROQ_API_KEY_VARIABLE = "GROQ_API_KEY"
GROQ_API_KEY_ALIASES = AliasChoices(
    GROQ_API_KEY_VARIABLE, f"{ENV_PREFIX}{GROQ_API_KEY_VARIABLE}", GROQ_API_KEY_FIELD
)
MIN_TEMPERATURE = 0.0
MAX_TEMPERATURE = 2.0
MIN_TIMEOUT_SECONDS = 0.0
MIN_COMPLETION_TOKENS = 1
MIN_BASE_URL_CHARS = 1

type ReasoningEffort = Literal["low", "medium", "high"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=ENV_FILE,
        env_file_encoding=ENV_FILE_ENCODING,
        extra="ignore",
    )

    data_dir: Path = DEFAULT_DATA_DIR
    debug: bool = False
    groq_api_key: SecretStr | None = Field(default=None, validation_alias=GROQ_API_KEY_ALIASES)
    model: str = "openai/gpt-oss-120b"
    fallback_model: str | None = None
    llm_base_url: str = Field(
        default="https://api.groq.com/openai/v1", min_length=MIN_BASE_URL_CHARS
    )
    llm_timeout_seconds: float = Field(default=60.0, gt=MIN_TIMEOUT_SECONDS)
    max_completion_tokens: int = Field(default=1024, ge=MIN_COMPLETION_TOKENS)
    reasoning_effort: ReasoningEffort = "low"
    temperature: float = Field(default=0.3, ge=MIN_TEMPERATURE, le=MAX_TEMPERATURE)
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


def variable_name_of(field_name: str) -> str:
    if field_name == GROQ_API_KEY_FIELD:
        return GROQ_API_KEY_VARIABLE
    return f"{ENV_PREFIX}{field_name.upper()}"


def invalid_variable_names(error: ValidationError) -> tuple[str, ...]:
    fields = dict.fromkeys(str(detail["loc"][0]) for detail in error.errors() if detail["loc"])
    return tuple(variable_name_of(field_name) for field_name in fields)
