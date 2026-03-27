"""URL normalization and extraction utilities.

Provides functions for normalizing URLs (removing www, standardizing paths),
extracting domains, and extracting paths for comparison purposes.
"""

from urllib.parse import urlparse


def normalize_url(u: str) -> str:
    """Normalize URL for comparison by removing www prefix and standardizing
    paths.

    Args:
        u: URL string to normalize

    Returns:
        Normalized URL string
    """
    try:
        scheme = urlparse(u).scheme
        return f'{scheme}://{extract_domain(u)}{extract_path(u)}'
    except Exception:
        return u.lower()


def extract_domain(u: str) -> str:
    """Extract normalized domain from URL.

    Args:
        u: URL string

    Returns:
        Normalized domain string (lowercase, www removed)
    """
    try:
        parsed = urlparse(u)
        domain = parsed.netloc.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain
    except Exception:
        return ''


def extract_path(u: str) -> str:
    """Extract normalized path from URL.

    Args:
        u: URL string

    Returns:
        Path string with trailing slash removed
    """
    try:
        parsed = urlparse(u)
        return parsed.path.rstrip('/')
    except Exception:
        return ''
