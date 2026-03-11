"""Application configuration."""
import os
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# Load .env into os.environ so os.getenv() can access all keys,
# including dynamic per-model keys like LLM_API_KEY_INTERN_S1_PRO.
# pydantic_settings only populates declared fields, not os.environ.
load_dotenv(override=False)

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database Configuration
    # 支持两种方式：
    # 1. 直接提供 DATABASE_URL (完整连接字符串)
    # 2. 分别提供 DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME (K8s 推荐)
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
    LLM_AVAILABLE_MODELS: str = 'gpt-4o-mini,gpt-4o'
    LLM_DEFAULT_MODEL: str = 'gpt-4o-mini'
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
    MAX_CONCURRENT_JOBS: int = 5     # 系统同时执行的 Job 数量上限
    DEFAULT_WORKERS: int = 1         # 单个 Job 内部的默认并行 Case 数
    MAX_WORKERS: int = 5             # 单个 Job 内部的最大并行 Case 数
    WEBQA_CASE_TIMEOUT: int = 2400   # 单个 Case 超时（秒），默认 40 分钟

    # Execution Mode: "local" / "docker" / "kubernetes"
    # - local: 启动子进程运行 Agent（本地开发）
    # - docker: 启动 Docker 容器运行 Agent（Docker Compose）
    # - kubernetes: 创建 K8s Job 运行 Agent（K8s 集群）
    EXECUTION_MODE: str = 'local'

    # Shared Storage Configuration
    # - 本地开发: 留空或设置为项目内路径 (如 ./data)
    # - Docker Compose / K8s: /shared
    SHARED_STORAGE_PATH: str = ''  # 留空则使用项目内 data 目录
    SHARED_REPORTS_DIR: str = 'reports'   # 报告子目录
    SHARED_LOGS_DIR: str = 'logs'         # 日志子目录

    # Backend Callback URL (供 Agent Job 回调使用)
    BACKEND_CALLBACK_URL: str = 'http://localhost:8000'

    # Feishu Webhook (默认飞书通知地址，定时任务未单独配置时使用)
    DEFAULT_FEISHU_WEBHOOK_URL: str = 'https://open.feishu.cn/open-apis/bot/v2/hook/ea37e263-8e8b-4b9a-b98d-cd0b6ad4f4fc'
    FEISHU_WEBHOOK_TIMEOUT_SECONDS: int = 10

    # Redis Configuration
    # 支持两种方式：
    # 1. 直接提供 REDIS_URL (完整连接字符串)
    # 2. 分别提供 REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_DB (K8s 推荐)
    REDIS_URL: Optional[str] = None
    REDIS_HOST: str = 'localhost'
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ''
    REDIS_DB: int = 0
    PROGRESS_CACHE_TTL: int = 43200  # 进度缓存 TTL（秒），执行完成后仍可查看 12 小时

    @property
    def database_url(self) -> str:
        """Get database URL, construct from components if not provided
        directly."""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        # 构建 DATABASE_URL from components
        from urllib.parse import quote_plus
        password = quote_plus(self.DB_PASSWORD)
        return f'postgresql+asyncpg://{self.DB_USER}:{password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}'

    @property
    def redis_url(self) -> str:
        """Get Redis URL, construct from components if not provided
        directly."""
        if self.REDIS_URL:
            return self.REDIS_URL
        # 构建 REDIS_URL from components
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
        """Get list of available models for Gen (AI探索) mode.

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
        LLM_API_KEY_INTERN_S1_PRO for 'intern-s1-pro'), falls back to
        LLM_API_KEY if not found.
        """
        normalized = model.upper().replace('-', '_').replace('.', '_')
        return os.getenv(f'LLM_API_KEY_{normalized}', self.LLM_API_KEY)

    def get_base_url_for_model(self, model: str) -> str:
        """Get base URL for a specific model.

        Looks up LLM_BASE_URL_<MODEL_NORMALIZED> env var first (e.g.
        LLM_BASE_URL_INTERN_S1_PRO for 'intern-s1-pro'), falls back to
        LLM_BASE_URL if not found.
        """
        normalized = model.upper().replace('-', '_').replace('.', '_')
        return os.getenv(f'LLM_BASE_URL_{normalized}', self.LLM_BASE_URL)

    @property
    def is_kubernetes_mode(self) -> bool:
        """Check if running in Kubernetes mode."""
        return self.EXECUTION_MODE.lower() == 'kubernetes'

    @property
    def effective_shared_storage_path(self) -> str:
        """Get effective shared storage path.

        如果 SHARED_STORAGE_PATH 为空，使用项目内的 data 目录（适用于本地开发）。
        """
        if self.SHARED_STORAGE_PATH:
            return self.SHARED_STORAGE_PATH
        # 本地开发默认使用项目内 data 目录
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
        env_file = '.env'
        env_file_encoding = 'utf-8'
        extra = 'ignore'


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
