import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _get_env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip()


def _get_bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _coerce_endpoint(value: str) -> str:
    normalized = value.lower()
    if normalized in {"search", "top-headlines"}:
        return normalized
    return "search"


def _require_env(name: str) -> str:
    """Retorna o valor de uma variavel obrigatoria ou levanta erro claro no startup."""
    value = os.getenv(name, "").strip()
    if not value:
        raise EnvironmentError(
            f"Variavel de ambiente obrigatoria '{name}' nao esta configurada. "
            f"Copie o .env.example para .env e preencha o valor."
        )
    return value


# GNews
API_KEY: str = _get_env("GNEWS_API_KEY")  # Validado em tempo de chamada no GNewsClient
BASE_URL: str = "https://gnews.io/api/v4"
DEFAULT_ENDPOINT: str = _coerce_endpoint(_get_env("GNEWS_ENDPOINT", "search"))
DEFAULT_LANGUAGE: str = _get_env("GNEWS_LANGUAGE", "pt")
DEFAULT_COUNTRY: str = _get_env("GNEWS_COUNTRY", "br")
DEFAULT_MAX_RESULTS: int = int(_get_env("GNEWS_MAX_RESULTS", "10"))

# MongoDB
MONGODB_URI: str = _get_env("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB_NAME: str = _get_env("MONGODB_DB_NAME", "brchain")
USE_MOCK_DB: bool = _get_bool_env("USE_MOCK_DB", False)
DEFAULT_USER_ID: str = _get_env("DEFAULT_USER_ID", "demo-user")

# Deduplicacao
TOP_QUERY_CATEGORIES: int = int(_get_env("TOP_QUERY_CATEGORIES", "3"))
TITLE_SIMILARITY_THRESHOLD: float = float(_get_env("TITLE_SIMILARITY_THRESHOLD", "0.85"))
RECENT_DEDUP_LOOKBACK_DAYS: int = int(_get_env("RECENT_DEDUP_LOOKBACK_DAYS", "7"))
DEDUP_CANDIDATE_LIMIT: int = int(_get_env("DEDUP_CANDIDATE_LIMIT", "200"))
RECENT_ARTICLES_LIMIT: int = int(_get_env("RECENT_ARTICLES_LIMIT", "120"))

# Ranking
PREFERENCE_SATURATION: float = float(_get_env("PREFERENCE_SATURATION", "4.0"))
TOPIC_DIVERSITY_PENALTY: float = float(_get_env("TOPIC_DIVERSITY_PENALTY", "0.45"))
FRESHNESS_HALF_LIFE_HOURS: float = float(_get_env("FRESHNESS_HALF_LIFE_HOURS", "24"))

# Feed
DEFAULT_FEED_LIMIT: int = int(_get_env("DEFAULT_FEED_LIMIT", "20"))
DEFAULT_ARTICLE_LIMIT: int = int(_get_env("DEFAULT_ARTICLE_LIMIT", "50"))
DEFAULT_EVENT_LIMIT: int = int(_get_env("DEFAULT_EVENT_LIMIT", "10"))

# API
API_HOST: str = _get_env("API_HOST", "127.0.0.1")
API_PORT: int = int(_get_env("API_PORT", "8000"))
API_RELOAD: bool = _get_bool_env("API_RELOAD", False)

# Scheduler
ENABLE_SCHEDULER: bool = _get_bool_env("ENABLE_SCHEDULER", False)
AUTO_INGEST_ON_STARTUP: bool = _get_bool_env("AUTO_INGEST_ON_STARTUP", False)
SCHEDULER_INTERVAL_MINUTES: int = int(_get_env("SCHEDULER_INTERVAL_MINUTES", "60"))

# Caminhos
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
TAGS_FILE: Path = PROJECT_ROOT / "Tags.json"
