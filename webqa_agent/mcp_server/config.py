"""MCP Server configuration via environment variables."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings for the WebQA MCP server."""

    api_url: str = 'http://localhost:8000'
    api_key: str = ''
    default_model: str = ''

    model_config = SettingsConfigDict(
        env_prefix='WEBQA_',
    )


settings = Settings()
