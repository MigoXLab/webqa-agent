"""Account registry and cookie resolution helpers."""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from webqa_agent.config_models.base_config import AccountConfig


class AccountPool:
    """Thread-safe account registry for reusable named identities."""

    def __init__(
        self,
        accounts: Optional[List[AccountConfig]] = None,
        fallback_cookies: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._accounts = {account.name: account for account in (accounts or [])}
        self._fallback_cookies = list(fallback_cookies or [])

        if len(self._accounts) != len(accounts or []):
            raise ValueError('Duplicate account names are not allowed')

        default_accounts = [account for account in (accounts or []) if account.default]
        if len(default_accounts) > 1:
            raise ValueError('Only one account can be marked as default')

        self._default_name = default_accounts[0].name if default_accounts else None

    def get(self, name: str) -> Optional[AccountConfig]:
        """Return an account by name."""
        with self._lock:
            return self._accounts.get(name)

    def get_default(self) -> Optional[AccountConfig]:
        """Return the default account if configured."""
        with self._lock:
            if not self._default_name:
                return None
            return self._accounts.get(self._default_name)

    def resolve_cookies(self, name: Optional[str]) -> Optional[List[Dict[str, Any]]]:
        """Resolve cookies in priority order: explicit name -> default -> fallback."""
        with self._lock:
            if name:
                account = self._accounts.get(name)
                return list(account.resolved_cookies) if account else None

            default_account = self.get_default()
            if default_account:
                return list(default_account.resolved_cookies)

            return list(self._fallback_cookies) if self._fallback_cookies else None

    def resolve_account_name(self, name: Optional[str]) -> Optional[str]:
        """Resolve the active account name if one is available."""
        if name:
            return name if name in self._accounts else None
        default_account = self.get_default()
        return default_account.name if default_account else None

    def get_role_summary(self) -> str:
        """Return a concise multi-line role summary for prompts."""
        with self._lock:
            if not self._accounts:
                return ''

            lines = []
            for account in self._accounts.values():
                default_tag = ' [default]' if account.default else ''
                role = account.role or 'No role description'
                description = f' - {account.description}' if account.description else ''
                lines.append(f"- {account.name}{default_tag}: {role}{description}")
            return '\n'.join(lines)

    @property
    def account_names(self) -> List[str]:
        """Return all registered account names."""
        with self._lock:
            return list(self._accounts.keys())

    @property
    def has_accounts(self) -> bool:
        """Whether the pool contains any named accounts."""
        with self._lock:
            return bool(self._accounts)
