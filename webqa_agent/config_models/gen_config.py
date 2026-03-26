"""Gen mode configuration for AI-driven test generation."""

from typing import List

from pydantic import BaseModel, Field

from webqa_agent.config_models.base_config import (BrowserConfig, LLMConfig,
                                                   LogConfig, ReportConfig)


class DynamicStepConfig(BaseModel):
    """Dynamic step generation configuration for adaptive testing."""

    enabled: bool = Field(default=True, description='Enable dynamic step generation')
    max_dynamic_steps: int = Field(
        default=8, ge=3, le=15, description='Maximum dynamic steps per UI change'
    )
    min_elements_threshold: int = Field(
        default=2, ge=1, le=5, description='Minimum new elements to trigger generation'
    )


class CustomToolsConfig(BaseModel):
    """Custom tools enable configuration.

    Default tools (execute_ui_action, execute_ui_assertion, execute_ux_verify)
    are always enabled. This config controls optional custom tools.
    """

    enabled: List[str] = Field(
        default_factory=list,
        description="List of custom tools to enable. Available: ['lighthouse', 'nuclei', 'traverse_clickable_elements', 'detect_dynamic_links']",
    )


class GenConfig(BaseModel):
    """Complete configuration for Gen mode (AI-driven test generation).

    Example:
        config = GenConfig(
            target_url="https://example.com",
            llm_config=LLMConfig(model="gpt-4o", api_key="sk-..."),
            business_objectives="Test search functionality",
            custom_tools=CustomToolsConfig(enabled=["lighthouse", "nuclei"])
        )
    """

    target_url: str = Field(..., description='Target URL to test')
    llm_config: LLMConfig = Field(..., description='LLM configuration')
    browser_config: BrowserConfig = Field(
        default_factory=BrowserConfig, description='Browser configuration'
    )
    report_config: ReportConfig = Field(
        default_factory=ReportConfig, description='Report configuration'
    )
    log_config: LogConfig = Field(
        default_factory=LogConfig, description='Logging configuration'
    )

    # Test configuration (flattened from FunctionTestConfig)
    business_objectives: str = Field(
        default='', description='Business objectives for test generation (optional)'
    )
    dynamic_step_generation: DynamicStepConfig = Field(
        default_factory=DynamicStepConfig, description='Dynamic step generation settings'
    )
    custom_tools: CustomToolsConfig = Field(
        default_factory=CustomToolsConfig, description='Custom tools to enable'
    )
    max_concurrent_tests: int = Field(
        default=4, ge=1, le=10, description='Maximum concurrent test execution'
    )

    skip_reflection: bool = Field(
        default=True, description='Skip reflection/self-correction phase'
    )
