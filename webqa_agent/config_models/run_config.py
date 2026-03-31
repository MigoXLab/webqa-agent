"""Run mode configuration for YAML case execution."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from webqa_agent.config_models.base_config import (AccountConfig, BrowserConfig, LLMConfig,
                                                   LogConfig, ReportConfig,
                                                   warn_if_dual_cookies)


class RunConfig(BaseModel):
    """Complete configuration for Run mode (YAML case execution).

    Example:
        config = RunConfig(
            llm_config=LLMConfig(model="gpt-4o", api_key="sk-..."),
            cases_path="/path/to/cases.yaml",
            workers=4
        )
    """

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
    cases_path: str = Field(..., description='Path to YAML test cases')
    workers: int = Field(default=1, ge=1, description='Number of parallel workers')
    accounts: Optional[List[AccountConfig]] = Field(
        default=None, description='Optional named browser accounts for multi-role testing'
    )
    ignore_rules: Optional[Dict[str, List[Dict[str, Any]]]] = Field(
        default=None, description='Rules to ignore specific test failures'
    )

    @model_validator(mode='after')
    def warn_dual_cookies(self) -> 'RunConfig':
        """Warn when both accounts and browser cookies are configured."""
        warn_if_dual_cookies(self.accounts, self.browser_config.cookies)
        return self
