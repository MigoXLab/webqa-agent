"""Base configuration models shared across Gen and Run modes."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class CloudConfig(BaseModel):
    """Cloud browser configuration for AgentBay integration."""

    enabled: bool = Field(default=False, description='Enable cloud browser mode')
    api_key: Optional[str] = Field(
        default=None, description='AgentBay API key (falls back to AGENTBAY_API_KEY env var)'
    )
    image_id: str = Field(default='browser_latest', description='AgentBay browser image ID')
    timeout: int = Field(default=30, ge=5, le=300, description='CDP connection timeout in seconds')


class BrowserConfig(BaseModel):
    """Browser configuration with unified cookies management.

    This is the single source of truth for browser settings and cookies.
    Supports two modes:
    - Local: Launches Playwright chromium locally
    - Cloud: Connects to AgentBay cloud browser via CDP
    """

    browser_type: str = Field(default='chromium', description='Browser engine type')
    headless: bool = Field(default=True, description='Run browser in headless mode')
    viewport: Dict[str, int] = Field(
        default={'width': 1280, 'height': 720}, description='Browser viewport size'
    )
    language: str = Field(default='en-US', description='Browser language')
    cookies: Optional[List[Dict[str, Any]]] = Field(
        default=None, description='Browser cookies (single source of truth)'
    )
    cloud_config: Optional[CloudConfig] = Field(
        default=None, description='Cloud browser configuration (AgentBay)'
    )

    @field_validator('viewport')
    @classmethod
    def validate_viewport(cls, v):
        """Validate viewport dimensions."""
        if v.get('width', 0) < 100 or v.get('height', 0) < 100:
            raise ValueError('Viewport dimensions must be at least 100x100')
        return v


class ReportConfig(BaseModel):
    """Report configuration for test results."""

    language: str = Field(default='zh-CN', description='Report language (en-US or zh-CN)')
    report_dir: Optional[str] = Field(
        default=None, description='Custom report directory (auto-generated if None)'
    )
    save_screenshots: bool = Field(
        default=False, description='Save screenshots during test execution'
    )
    save_dataflow: bool = Field(
        default=True,
        description='Record data-flow events (JSONL) and generate interactive gantt report.',
    )

    @field_validator('language')
    @classmethod
    def validate_language(cls, v):
        """Validate language is supported."""
        if v not in ['en-US', 'zh-CN']:
            raise ValueError(f"Unsupported language: {v}. Must be 'en-US' or 'zh-CN'")
        return v


class LLMConfig(BaseModel):
    """LLM configuration with provider detection and validation."""

    model: str = Field(..., description='LLM model name')
    filter_model: Optional[str] = Field(
        default=None, description='Lightweight model for element filtering'
    )
    api_key: str = Field(..., description='API key for LLM provider')
    base_url: Optional[str] = Field(default=None, description='Custom API endpoint')
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0, description='Sampling temperature')
    max_tokens: Optional[int] = Field(default=None, gt=0, description='Maximum output tokens')
    reasoning: Optional[Dict[str, Any]] = Field(
        default=None, description='Extended thinking configuration (Claude/OpenAI)'
    )
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0, description='Nucleus sampling parameter')
    text: Optional[Dict[str, Any]] = Field(default=None, description='Text generation options (GPT-5)')
    timeout: Optional[int] = Field(default=None, gt=0, description='LLM request timeout in seconds')

    @field_validator('api_key')
    @classmethod
    def validate_api_key(cls, v):
        """Validate API key is not placeholder."""
        if not v or v in [
            'your_openai_api_key',
            'your_anthropic_api_key',
            'your_gemini_api_key',
        ]:
            raise ValueError(
                'Invalid API key. Please set a valid API key or environment variable '
                '(OPENAI_API_KEY, ANTHROPIC_API_KEY, or GEMINI_API_KEY)'
            )
        return v

    @field_validator('reasoning')
    @classmethod
    def validate_reasoning(cls, v, info):
        """Validate Extended Thinking configuration (Claude/OpenAI)."""
        if v is None:
            return v

        effort = v.get('effort')
        if effort not in ['minimal', 'low', 'medium', 'high']:
            raise ValueError(f'Invalid reasoning effort: {effort}. Must be minimal/low/medium/high')

        # For Claude Extended Thinking, enforce temperature=1.0
        model = info.data.get('model', '')
        if model.startswith('claude-'):
            temperature = info.data.get('temperature')
            if temperature is not None and temperature != 1.0:
                raise ValueError(
                    'Claude Extended Thinking requires temperature=1.0. '
                    'This will be automatically enforced.'
                )

            # Validate max_tokens > budget_tokens
            max_tokens = info.data.get('max_tokens')
            budget_map = {'minimal': 1024, 'low': 4096, 'medium': 10000, 'high': 20000}
            budget_tokens = budget_map.get(effort, 10000)

            if max_tokens and max_tokens <= budget_tokens:
                raise ValueError(
                    f'max_tokens ({max_tokens}) must be greater than reasoning budget_tokens ({budget_tokens}). '
                    f"Recommended max_tokens for effort='{effort}': {budget_tokens * 2}"
                )

        return v

    def get_provider(self) -> str:
        """Detect LLM provider from model name."""
        model_lower = self.model.lower()
        if model_lower.startswith('claude-'):
            return 'anthropic'
        elif model_lower.startswith('gemini-'):
            return 'gemini'
        elif model_lower.startswith('gpt-'):
            return 'openai'
        else:
            return 'openai'  # Default to OpenAI

    def get_default_temperature(self) -> float:
        """Get provider-specific default temperature."""
        provider = self.get_provider()
        if provider == 'openai':
            return 0.1
        else:  # anthropic, gemini
            return 1.0


class LogConfig(BaseModel):
    """Logging configuration for application logs."""

    level: str = Field(
        default='info', description='Log level (debug, info, warning, error)'
    )
    stdout: bool = Field(
        default=False,
        description='Disable file logging, only stdout'
    )

    @field_validator('level')
    @classmethod
    def validate_level(cls, v):
        """Validate log level is valid."""
        valid_levels = ['debug', 'info', 'warning', 'error']
        v_lower = v.lower()
        if v_lower not in valid_levels:
            raise ValueError(
                f'Invalid log level: {v}. Must be one of {valid_levels}'
            )
        return v_lower
