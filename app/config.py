import os
from dotenv import load_dotenv

load_dotenv()


def get_float_env(name: str, default: float) -> float:
    """
    Lee una variable de entorno numérica.

    Si la variable no existe o no es válida, devuelve el valor por defecto.
    """

    raw_value = os.getenv(name)

    if raw_value is None or not raw_value.strip():
        return default

    try:
        return float(raw_value)
    except ValueError:
        return default


def get_int_env(name: str, default: int) -> int:
    """Read an integer environment variable with a safe default."""

    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default

    try:
        return int(raw_value)
    except ValueError:
        return default


class Settings:
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    OPENAI_TIMEOUT: float = get_float_env("OPENAI_TIMEOUT", 30.0)
    MAX_REPAIR_ATTEMPTS: int = get_int_env("MAX_REPAIR_ATTEMPTS", 3)
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./odrl_translator.db")


settings = Settings()