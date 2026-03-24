"""Authentication provider interface and default implementation.

Provider implementations must expose:
- name: str - provider identifier
- generate_cookies(username, password, env) -> list[dict] - generate browser cookies
"""
import logging
from typing import Dict, List, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class AuthProvider(Protocol):
    """Protocol for browser authentication providers."""

    name: str

    def generate_cookies(
        self, username: str, password: str, env: str = 'prod'
    ) -> List[Dict]:
        """Generate browser cookies from credentials.

        Args:
            username: Login username
            password: Login password
            env: Target environment (e.g. 'prod', 'staging')

        Returns:
            List of cookie dicts: [{"name": str, "value": str, "domain": str, "path": str}]
        """
        ...


class CookiesAuthProvider:
    """Default provider: users configure cookies directly in environment settings.

    This provider does not support generating cookies from username/password.
    Users should set auth_type='cookies' and provide cookies in the environment config.
    """

    name = 'cookies'

    def generate_cookies(
        self, username: str, password: str, env: str = 'prod'
    ) -> List[Dict]:
        raise NotImplementedError(
            'Cookie-based auth does not support generating cookies from credentials. '
            'Please configure cookies directly in the environment settings, '
            'or install an auth provider extension (e.g. OAuth, SSO).'
        )
