"""URL validation utility for preventing LLM-generated URL hallucinations.

This module provides URL validation against the test session's base URL to prevent
common issues like domain name reordering or incorrect scheme usage.

Architecture:
- Used by ActionHandler to validate URLs before navigation
- Initialized with test session's target_url from config
- Provides both validation and auto-correction capabilities

Key Features:
- Domain validation (ensures target matches base domain)
- Scheme validation (http/https required)
- Auto-correction for fixable issues
- Detailed error messages for debugging

Example:
    validator = URLValidator("https://discovery.intern-ai.org.cn/home")

    # Validation only
    is_valid, error = validator.validate("https://intern-discovery.org.cn/")
    # Returns: (False, "Domain mismatch: expected 'discovery.intern-ai.org.cn', got 'intern-discovery.org.cn'")

    # Validation with auto-fix
    try:
        fixed_url = validator.validate_or_fix("/login")
        # Returns: "https://discovery.intern-ai.org.cn/login"
    except ValueError as e:
        print(f"Cannot fix: {e}")
"""

import logging
from typing import Optional, Tuple
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)


class URLValidator:
    """Validates generated URLs against the test session's base URL.

    This prevents LLM hallucinations where domain names are incorrectly
    reordered or modified (e.g., "intern-discovery" instead of "discovery.intern-ai").

    Attributes:
        base_url: The test session's starting URL (e.g., config.target_url)
        base_domain: Extracted domain without scheme or path
        base_scheme: Scheme from base URL (http or https)
    """

    def __init__(self, base_url: str):
        """Initialize URL validator with test session's base URL.

        Args:
            base_url: The test session's starting URL (e.g., config.target_url)
                     Should be a valid absolute URL with scheme.

        Raises:
            ValueError: If base_url is invalid or missing scheme
        """
        if not base_url:
            raise ValueError('Base URL cannot be empty')

        parsed = urlparse(base_url)
        if not parsed.scheme:
            raise ValueError(f'Base URL must include scheme (http/https): {base_url}')
        if not parsed.netloc:
            raise ValueError(f'Base URL must include domain: {base_url}')

        self.base_url = base_url
        self.base_domain = parsed.netloc
        self.base_scheme = parsed.scheme

        logger.debug(
            f'URLValidator initialized: domain={self.base_domain}, scheme={self.base_scheme}'
        )

    def validate(self, url: str) -> Tuple[bool, Optional[str]]:
        """Validate URL against base domain.

        Args:
            url: URL to validate (can be absolute or relative)

        Returns:
            Tuple of (is_valid, error_message)
            - (True, None) if valid
            - (False, error_message) if invalid

        Examples:
            >>> validator = URLValidator("https://discovery.intern-ai.org.cn/home")
            >>> validator.validate("https://discovery.intern-ai.org.cn/login")
            (True, None)
            >>> validator.validate("https://intern-discovery.org.cn/")
            (False, "Domain mismatch: expected 'discovery.intern-ai.org.cn', got 'intern-discovery.org.cn'")
        """
        if not url:
            return False, 'Empty URL'

        # Handle relative URLs (these are always valid - will use current domain)
        if url.startswith('/'):
            return True, None

        # Parse absolute URL
        parsed = urlparse(url)

        # Check 1: Must have scheme for absolute URLs
        if not parsed.scheme:
            return False, 'Absolute URL must include scheme (http/https)'

        # Check 2: Must have domain for absolute URLs
        if not parsed.netloc:
            return False, 'Absolute URL must include domain'

        # Check 3: Domain must match base domain
        if parsed.netloc != self.base_domain:
            return (
                False,
                f"Domain mismatch: expected '{self.base_domain}', got '{parsed.netloc}'"
            )

        # Check 4: Scheme should match (warning only, not error)
        if parsed.scheme != self.base_scheme:
            logger.warning(
                f"Scheme mismatch: base uses '{self.base_scheme}', "
                f"target uses '{parsed.scheme}' for URL: {url}"
            )

        return True, None

    def validate_or_fix(self, url: str) -> str:
        """Validate URL and attempt to fix if invalid.

        This method attempts to auto-correct common URL issues:
        1. Relative paths -> Absolute URLs with base domain
        2. Wrong domain with same path -> Use base domain instead

        Args:
            url: URL to validate and potentially fix

        Returns:
            Corrected URL (same as input if already valid)

        Raises:
            ValueError: If URL cannot be validated or fixed

        Examples:
            >>> validator = URLValidator("https://discovery.intern-ai.org.cn/home")

            # Relative path -> Absolute URL
            >>> validator.validate_or_fix("/login")
            "https://discovery.intern-ai.org.cn/login"

            # Wrong domain -> Auto-corrected
            >>> validator.validate_or_fix("https://intern-discovery.org.cn/login")
            "https://discovery.intern-ai.org.cn/login"

            # Already valid -> No change
            >>> validator.validate_or_fix("https://discovery.intern-ai.org.cn/login")
            "https://discovery.intern-ai.org.cn/login"
        """
        # Fix 1: Relative path -> Make absolute with base domain
        # Do this BEFORE validation, as validate() returns True for relative paths
        if url.startswith('/'):
            fixed_url = f'{self.base_scheme}://{self.base_domain}{url}'
            logger.info(f'URL auto-corrected (relative->absolute): {url} -> {fixed_url}')
            return fixed_url

        # Validate absolute URLs
        is_valid, error = self.validate(url)
        if is_valid:
            return url

        # Attempt to fix common issues
        parsed = urlparse(url)

        # Fix 2: Wrong domain but has path -> Use base domain with target path
        if parsed.path and parsed.netloc != self.base_domain:
            # Reconstruct URL with base domain
            fixed_parts = (
                self.base_scheme,  # Use base scheme
                self.base_domain,   # Use base domain
                parsed.path,        # Keep original path
                parsed.params,      # Keep params
                parsed.query,       # Keep query
                parsed.fragment     # Keep fragment
            )
            fixed_url = urlunparse(fixed_parts)

            # Verify the fix is valid
            is_valid_fixed, _ = self.validate(fixed_url)
            if is_valid_fixed:
                logger.warning(
                    f'URL auto-corrected (wrong domain): {url} -> {fixed_url}'
                )
                return fixed_url

        # Cannot fix - raise error with context
        raise ValueError(f'Invalid URL: {url}. {error}')

    def is_same_domain(self, url: str) -> bool:
        """Check if URL belongs to the same domain as base URL.

        Args:
            url: URL to check

        Returns:
            True if URL has same domain as base_url, False otherwise

        Examples:
            >>> validator = URLValidator("https://discovery.intern-ai.org.cn/home")
            >>> validator.is_same_domain("https://discovery.intern-ai.org.cn/login")
            True
            >>> validator.is_same_domain("https://google.com")
            False
        """
        is_valid, _ = self.validate(url)
        return is_valid
