# SPDX-License-Identifier: Apache-2.0
# Portions adapted from cc-mini (https://github.com/e10nMa2k/cc-mini)
# Original author: e10nMa2k. Modifications © 2026 WebQA Agent contributors.
"""Stub permission checker for the library-mode web agent.

In library usage, callers are trusted and permission gating is handled by:
  1. Domain whitelist at the MCP server launch layer (user-data-dir / CDP flags)
  2. Caller-side interception via the ``on_event`` callback in runner.py

This stub always returns "allow" to keep engine.py's check() call sites working
without changes.
"""
from __future__ import annotations

from typing import Literal

from .tool import Tool

PermissionBehavior = Literal['allow', 'deny']


class PermissionChecker:
    def check(self, tool: Tool, tool_input: dict) -> PermissionBehavior:
        return 'allow'
