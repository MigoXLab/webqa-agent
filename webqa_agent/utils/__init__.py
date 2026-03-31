"""WebQA Agent Utilities.

This module provides various utility functions for the WebQA Agent.
"""

# Configuration utilities
from webqa_agent.utils.config import (find_config_file, load_accounts,
                                      load_cookies, load_yaml, load_yaml_files,
                                      resolve_config_dir)
# Display utilities
from webqa_agent.utils.task_display_util import Display

display_context = Display.display


def check_lighthouse_installation(*args, **kwargs):
    """Lazy wrapper to avoid importing optional deps at module import time."""
    from webqa_agent.utils.dependency import check_lighthouse_installation as _impl
    return _impl(*args, **kwargs)


def check_nuclei_installation(*args, **kwargs):
    """Lazy wrapper to avoid importing optional deps at module import time."""
    from webqa_agent.utils.dependency import check_nuclei_installation as _impl
    return _impl(*args, **kwargs)


async def check_playwright_browsers_async(*args, **kwargs):
    """Lazy wrapper to avoid importing optional deps at module import time."""
    from webqa_agent.utils.dependency import check_playwright_browsers_async as _impl
    return await _impl(*args, **kwargs)

__all__ = [
    # Config
    'find_config_file',
    'load_accounts',
    'load_cookies',
    'load_yaml',
    'load_yaml_files',
    'resolve_config_dir',
    # Dependency
    'check_lighthouse_installation',
    'check_nuclei_installation',
    'check_playwright_browsers_async',
    # Display
    'Display',
    'display_context',
]
