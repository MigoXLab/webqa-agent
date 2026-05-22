# SPDX-License-Identifier: Apache-2.0
# Portions adapted from cc-mini (https://github.com/e10nMa2k/cc-mini)
# Original author: e10nMa2k. Modifications © 2026 WebQA Agent contributors.
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    content: str
    is_error: bool = False
    content_blocks: list[dict[str, Any]] = field(default_factory=list)


class Tool(ABC):
    # Default opt-in for concurrent execution within a read-only batch.
    # Subclasses set False when the underlying backend serialises despite
    # being logically read-only (e.g. chrome-devtools-mcp on a single page),
    # or when the tool keeps mutable instance state (e.g. DownloadCheckTool).
    # MCPTool overrides per-instance in __init__.
    concurrent_safe: bool = True

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        ...

    @property
    @abstractmethod
    def input_schema(self) -> dict:
        ...

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        ...

    def get_activity_description(self, **kwargs) -> str | None:
        """Return a human-readable description of what the tool is doing, shown
        in the spinner."""
        return None

    def is_read_only(self) -> bool:
        return False

    def to_api_schema(self) -> dict:
        return {
            'name': self.name,
            'description': self.description,
            'input_schema': self.input_schema,
        }
