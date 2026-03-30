"""Application configuration."""
import os
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# backend/ directory (config.py is in backend/app/, so two levels up is backend/)
BACKEND_DIR = Path(__file__).parent.parent.resolve()
DOTENV_PATH = BACKEND_DIR / '.env'

# Load .env into os.environ so os.getenv() can access all keys,
# including dynamic per-model keys like LLM_API_KEY_CUSTOM_MODEL.
# pydantic_settings only populates declared fields, not os.environ.
load_dotenv(DOTENV_PATH, override=False)

# Project root directory
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database Configuration
    # Supports two methods:
    # 1. Provide DATABASE_URL directly (full connection string)
    # 2. Provide DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME separately (recommended for K8s)
    DATABASE_URL: Optional[str] = None
    DB_HOST: str = 'localhost'
    DB_PORT: int = 5432
    DB_USER: str = 'postgres'
    DB_PASSWORD: str = 'postgres'
    DB_NAME: str = 'webqa'

    # LLM Configuration
    LLM_API: str = 'openai'
    LLM_API_KEY: str = ''
    LLM_BASE_URL: str = 'https://api.openai.com/v1'
    LLM_AVAILABLE_MODELS: str = 'gemini-3-flash-preview,gemini-3.1-flash-lite-preview,gpt-5-mini-2025-08-07,doubao-seed-2-0-pro-260215'
    LLM_DEFAULT_MODEL: str = 'gpt-5-mini-2025-08-07'
    LLM_GEN_MODELS: str = ''
    LLM_GEN_DEFAULT_MODEL: str = ''

    # OSS Configuration
    OSS_ENDPOINT: str = ''
    OSS_BUCKET: str = ''
    OSS_ACCESS_KEY_ID: str = ''
    OSS_ACCESS_KEY_SECRET: str = ''
    OSS_PUBLIC_URL_PREFIX: str = ''

    # Execution Control
    JOB_TIMEOUT_SECONDS: int = 7200  # 2 hours
    MAX_CONCURRENT_JOBS: int = 5     # Maximum number of concurrent jobs in the system
    DEFAULT_WORKERS: int = 1         # Default number of parallel cases within a single job
    MAX_WORKERS: int = 5             # Maximum number of parallel cases within a single job
    WEBQA_CASE_TIMEOUT: int = 2400   # Timeout for a single case (seconds), default 40 minutes

    # Execution Mode: "local" / "docker" / "kubernetes"
    # - local: Start subprocess to run Agent (local development)
    # - docker: Start Docker container to run Agent (Docker Compose)
    # - kubernetes: Create K8s Job to run Agent (K8s cluster)
    EXECUTION_MODE: str = 'local'

    # Docker Mode Configuration
    DOCKER_AGENT_IMAGE: str = 'webqa-agent:latest'
    DOCKER_NETWORK: str = 'webqa-network'
    DOCKER_SHARED_VOLUME: str = 'webqa-shared-data'

    # Shared Storage Configuration
    # - Local development: Leave empty or set to path within project (e.g., ./data)
    # - Docker Compose / K8s: /shared
    SHARED_STORAGE_PATH: str = ''  # If empty, uses data directory within project
    SHARED_REPORTS_DIR: str = 'reports'   # Reports subdirectory
    SHARED_LOGS_DIR: str = 'logs'         # Logs subdirectory

    # Backend Callback URL (used by Agent Job callback)
    BACKEND_CALLBACK_URL: str = 'http://localhost:8000'

    # Notification Webhook (used by notification provider for scheduled task results)
    DEFAULT_FEISHU_WEBHOOK_URL: str = ''
    FEISHU_WEBHOOK_TIMEOUT_SECONDS: int = 10

    # Redis Configuration
    # Supports two methods:
    # 1. Provide REDIS_URL directly (full connection string)
    # 2. Provide REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_DB separately (recommended for K8s)
    REDIS_URL: Optional[str] = None
    REDIS_HOST: str = 'localhost'
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ''
    REDIS_DB: int = 0
    PROGRESS_CACHE_TTL: int = 43200  # Progress cache TTL (seconds), viewable for 12 hours after completion

    @property
    def database_url(self) -> str:
        """Get database URL, construct from components if not provided
        directly."""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        # Build DATABASE_URL from components
        from urllib.parse import quote_plus
        password = quote_plus(self.DB_PASSWORD)
        return f'postgresql+asyncpg://{self.DB_USER}:{password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}'

    @property
    def redis_url(self) -> str:
        """Get Redis URL, construct from components if not provided
        directly."""
        if self.REDIS_URL:
            return self.REDIS_URL
        # Build REDIS_URL from components
        if self.REDIS_PASSWORD:
            return f'redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}'
        else:
            return f'redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}'

    @property
    def available_models(self) -> List[str]:
        """Get list of available models for Run mode."""
        return [m.strip() for m in self.LLM_AVAILABLE_MODELS.split(',') if m.strip()]

    @property
    def gen_models(self) -> List[str]:
        """Get list of available models for Gen (AI exploration) mode.

        Falls back to available_models if LLM_GEN_MODELS is not set.
        """
        if self.LLM_GEN_MODELS.strip():
            return [m.strip() for m in self.LLM_GEN_MODELS.split(',') if m.strip()]
        return self.available_models

    @property
    def gen_default_model(self) -> str:
        """Get default model for Gen mode.

        Falls back to LLM_DEFAULT_MODEL if not set.
        """
        return self.LLM_GEN_DEFAULT_MODEL.strip() or self.LLM_DEFAULT_MODEL

    def get_api_key_for_model(self, model: str) -> str:
        """Get API key for a specific model.

        Looks up LLM_API_KEY_<MODEL_NORMALIZED> env var first (e.g.
        LLM_API_KEY_CUSTOM_MODEL for 'custom-model'), falls back to LLM_API_KEY
        if not found.
        """
        normalized = model.upper().replace('-', '_').replace('.', '_')
        return os.getenv(f'LLM_API_KEY_{normalized}', self.LLM_API_KEY)

    def get_base_url_for_model(self, model: str) -> str:
        """Get base URL for a specific model.

        Looks up LLM_BASE_URL_<MODEL_NORMALIZED> env var first (e.g.
        LLM_BASE_URL_CUSTOM_MODEL for 'custom-model'), falls back to
        LLM_BASE_URL if not found.
        """
        normalized = model.upper().replace('-', '_').replace('.', '_')
        return os.getenv(f'LLM_BASE_URL_{normalized}', self.LLM_BASE_URL)

    @property
    def is_docker_mode(self) -> bool:
        """Check if running in Docker mode."""
        return self.EXECUTION_MODE.lower() == 'docker'

    @property
    def is_kubernetes_mode(self) -> bool:
        """Check if running in Kubernetes mode."""
        return self.EXECUTION_MODE.lower() == 'kubernetes'

    @property
    def effective_shared_storage_path(self) -> str:
        """Get effective shared storage path.

        If SHARED_STORAGE_PATH is empty, use the data directory within the
        project (for local development).
        """
        if self.SHARED_STORAGE_PATH:
            return self.SHARED_STORAGE_PATH
        # Local development defaults to using the data directory within the project
        return str(PROJECT_ROOT / 'data')

    @property
    def shared_reports_path(self) -> str:
        """Get shared reports directory path."""
        return f'{self.effective_shared_storage_path}/{self.SHARED_REPORTS_DIR}'

    @property
    def shared_logs_path(self) -> str:
        """Get shared logs directory path."""
        return f'{self.effective_shared_storage_path}/{self.SHARED_LOGS_DIR}'

    class Config:
        env_file = str(DOTENV_PATH)
        env_file_encoding = 'utf-8'
        extra = 'ignore'


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
