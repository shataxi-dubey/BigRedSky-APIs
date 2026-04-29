"""Configuration settings for the application"""

import enum
from typing import Union

from pydantic_settings import BaseSettings, SettingsConfigDict


class LogLevel(str, enum.Enum):
    """Defines available logging levels for application monitoring and debugging."""

    NOTSET = "NOTSET"
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    FATAL = "FATAL"
    TRACE = "TRACE"


class CacheBackend(str, enum.Enum):
    """Supported cache backends."""

    REDIS = "redis"
    LOCAL = "local"


class RateLimitBackend(str, enum.Enum):
    """Supported rate-limit backends."""

    REDIS = "redis"
    LOCAL = "local"


class AppEnvs(str, enum.Enum):
    """Application envs"""

    DEVELOPMENT = "development"
    QA = "qa"
    DEMO = "demo"
    PRODUCTION = "production"


class AppConfig(BaseSettings):
    """Primary configuration settings for the application."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    LOG_LEVEL: LogLevel = LogLevel.TRACE
    RELEASE_VERSION: str = "0.0.1"
    ENVIRONMENT: AppEnvs = AppEnvs.DEVELOPMENT
    HOST: str = "0.0.0.0"
    PORT: int = 8002
    WORKER_COUNT: Union[int, None] = None

    # Cache
    CACHE_BACKEND: CacheBackend = CacheBackend.LOCAL

    # Rate Limit
    RATE_LIMIT_BACKEND: RateLimitBackend = RateLimitBackend.REDIS

    # Redis
    REDIS_HOST: str = ""
    REDIS_PORT: str = ""
    REDIS_PASSWORD: str = ""

    # OPENAI Model
    OPENAI_API_KEY: str = ""
    TAVILY_API_KEY: str = ""

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/bigredsky"

    # JD Creator models
    JD_LLM_MODEL: str = "gpt-4.1"

    # Resume Parser models
    RESUME_LLM_MODEL: str = "gpt-4.1-mini"
    CHUNK_LLM_MODEL: str = "gpt-4.1-mini"
    # Dense embedding model (vector dimension is read from the loaded model at runtime)
    DENSE_EMBED_MODEL: str = "Qwen/Qwen3-Embedding-8b"
    # Sparse embedding model (SPLADE)
    SPARSE_EMBED_MODEL: str = "prithivida/Splade_PP_en_v1"

    # Qdrant
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""
    QDRANT_COLLECTION_NAME: str = "resume_chunks"

    # Local Model (LM Studio)
    LOCAL_MODEL_URL: str = "http://127.0.0.1:1234"
    USE_LOCAL_MODEL: bool = False  # Default to OpenAI, can be overridden

    # Search Provider Configuration
    SEARCH_PROVIDER: str = "duckduckgo"  # "duckduckgo" or "tavily"
    DUCKDUCKGO_MAX_RESULTS: int = 10

    # LangFuse
    LANGFUSE_HOST: str = ""
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""


# Initialize configuration settings
settings = AppConfig()
