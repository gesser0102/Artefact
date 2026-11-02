from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "EMPORIO_"
ENABLED_DEBUG_VALUES = frozenset({"1", "true", "yes", "on"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX)

    data_dir: Path = Path("data")
    debug: bool = False

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug_flag(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower() in ENABLED_DEBUG_VALUES
        return value
