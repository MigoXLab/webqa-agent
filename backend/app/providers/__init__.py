"""Provider abstraction layer for pluggable authentication, storage, and
notification.

Supports two loading strategies (in priority order):
1. Explicit: Set env var (e.g. AUTH_PROVIDER=custom_sso) to load a specific module
2. Default: Open-source fallback implementations (cookies auth, local storage, no notifications)
"""
import importlib
import logging
import os
from typing import Any

from .auth import AuthProvider, CookiesAuthProvider
from .notification import NoopNotifier, Notifier
from .storage import LocalStorageProvider, StorageProvider

__all__ = [
    'AuthProvider',
    'CookiesAuthProvider',
    'StorageProvider',
    'LocalStorageProvider',
    'Notifier',
    'NoopNotifier',
    'get_provider',
]

logger = logging.getLogger(__name__)

_registry: dict[str, Any] = {}

# Internal module paths for auto-detection.
# These modules exist in GitLab (internal) but not in GitHub (open-source).
_INTERNAL_MODULES: dict[str, str] = {
    'auth': 'app.utils.get_sso_token',
    'storage': 'app.utils.oss_utils',
    'notification': 'app.services.feishu_notify',
}

_DEFAULTS: dict[str, type] = {
    'auth': CookiesAuthProvider,
    'storage': LocalStorageProvider,
    'notification': NoopNotifier,
}


def _try_import(module_path: str) -> Any:
    """Try to import a module, return None on ImportError."""
    try:
        return importlib.import_module(module_path)
    except ImportError:
        return None
    except Exception as exc:
        logger.warning('[Provider] Error importing %s: %s', module_path, exc)
        return None


def get_provider(provider_type: str) -> Any:
    """Get a provider instance by type.

    Loading priority:
    1. If env var {TYPE}_PROVIDER is set (and not "auto"/"default"), load that module
    2. If env var is "auto" (default), try to import the internal implementation
    3. Fall back to the open-source default implementation

    Args:
        provider_type: One of "auth", "storage", "notification"

    Returns:
        Provider instance
    """
    if provider_type in _registry:
        return _registry[provider_type]

    if provider_type not in _DEFAULTS:
        raise ValueError(
            f'Unknown provider type: {provider_type!r}. '
            f'Must be one of: {", ".join(_DEFAULTS.keys())}'
        )

    env_key = f'{provider_type.upper()}_PROVIDER'
    provider_name = os.getenv(env_key, 'auto')
    instance = None

    # Strategy 1: Explicit provider name
    if provider_name not in ('auto', 'default'):
        mod = _try_import(f'app.providers.{provider_name}')
        if mod and hasattr(mod, 'Provider'):
            instance = mod.Provider()
            logger.info(
                '[Provider] %s → %s (explicit via %s)',
                provider_type, instance.__class__.__name__, env_key,
            )

    # Strategy 2: Auto-detect internal implementation
    if instance is None and provider_name == 'auto':
        internal_mod_path = _INTERNAL_MODULES.get(provider_type)
        if internal_mod_path:
            mod = _try_import(internal_mod_path)
            if mod and hasattr(mod, 'Provider'):
                instance = mod.Provider()
                logger.info(
                    '[Provider] %s → %s (auto-detected from %s)',
                    provider_type, instance.__class__.__name__, internal_mod_path,
                )

    # Strategy 3: Open-source default
    if instance is None:
        instance = _DEFAULTS[provider_type]()
        logger.info(
            '[Provider] %s → %s (default)',
            provider_type, instance.__class__.__name__,
        )

    _registry[provider_type] = instance
    return instance
