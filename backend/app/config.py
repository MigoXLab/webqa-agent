"""Application configuration."""
import os
from functools import lru_cache
from pathlib import Path
from typing import List, Literal, Optional

from pydantic_settings import BaseSettings

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    DATABASE_URL: str = 'postgresql+asyncpg://postgres:postgres@localhost:5432/webqa'

    # LLM Configuration
    LLM_API: str = 'openai'
    LLM_API_KEY: str = ''
    LLM_BASE_URL: str = 'https://api.openai.com/v1'
    LLM_AVAILABLE_MODELS: str = 'gpt-4o-mini,gpt-4o'
    LLM_DEFAULT_MODEL: str = 'gpt-4o-mini'

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

    # Redis Configuration (进度缓存)
    REDIS_URL: str = 'redis://localhost:6379/0'
    PROGRESS_CACHE_TTL: int = 36000  # 进度缓存 TTL（秒），执行完成后仍可查看 10 小时

    # CORS
    CORS_ORIGINS: str = 'http://localhost:3000,http://localhost:5173'

    @property
    def available_models(self) -> List[str]:
        """Get list of available models."""
        return [m.strip() for m in self.LLM_AVAILABLE_MODELS.split(',') if m.strip()]

    @property
    def cors_origins_list(self) -> List[str]:
        """Get list of CORS origins."""
        return [o.strip() for o in self.CORS_ORIGINS.split(',') if o.strip()]

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


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
