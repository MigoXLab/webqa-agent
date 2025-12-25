"""Dependency checking utilities.

This module provides utilities for checking external dependencies like
Playwright, Lighthouse, and Nuclei.
"""

import os
import subprocess

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright


async def check_playwright_browsers_async():
    """Check if Playwright browsers are installed.

    Returns:
        bool: True if browsers are available, False otherwise
    """
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            await browser.close()
        print('✅ Playwright browsers available')
        return True
    except PlaywrightError as e:
        print(f'⚠️ Playwright browsers unavailable: {e}')
        return False
    except Exception as e:
        print(f'❌ Playwright check failed: {e}')
        return False


def check_lighthouse_installation():
    """Check if Lighthouse is properly installed.

    Checks for Lighthouse in the following locations (in order):
    1. Local installation in current directory (node_modules/.bin)
    2. Local installation in script directory (node_modules/.bin)
    3. Docker container (/app/node_modules/.bin)
    4. Global installation (PATH)

    Returns:
        bool: True if Lighthouse is found, False otherwise
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    current_dir = os.getcwd()
    is_windows = os.name == 'nt'
    lighthouse_exe = 'lighthouse.cmd' if is_windows else 'lighthouse'

    # Possible lighthouse paths (local installation priority)
    lighthouse_paths = [
        os.path.join(current_dir, 'node_modules', '.bin', lighthouse_exe),  # local in current directory
        os.path.join(script_dir, 'node_modules', '.bin', lighthouse_exe),  # local in script directory
        'lighthouse',  # global installation path (fallback)
    ]

    if not is_windows:
        lighthouse_paths.insert(-1, os.path.join('/app', 'node_modules', '.bin', 'lighthouse'))

    for path in lighthouse_paths:
        try:
            result = subprocess.run([path, '--version'], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                version = result.stdout.strip()
                print(f'✅ Lighthouse available: {version}')
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            continue

    print('❌ Lighthouse not found')
    return False


def check_nuclei_installation():
    """Check if Nuclei is properly installed.

    Returns:
        bool: True if Nuclei is found, False otherwise
    """
    try:
        result = subprocess.run(['nuclei', '-version'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            version = result.stdout.strip()
            print(f'✅ Nuclei available: {version}')
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        pass
    print('❌ Nuclei not found')
    return False
