import os
from dotenv import load_dotenv

load_dotenv()


def _get_env(name: str, default, cast):
    """Read a numeric environment variable, falling back to `default` if it is missing or invalid."""

    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default

    try:
        return cast(raw_value)
    except ValueError:
        return default


class Settings:
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    OPENAI_TIMEOUT: float = _get_env("OPENAI_TIMEOUT", 30.0, float)
    MAX_REPAIR_ATTEMPTS: int = _get_env("MAX_REPAIR_ATTEMPTS", 3, int)
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./odrl_translator.db")


settings = Settings()