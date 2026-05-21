"""Account registry for cookie-based multi-identity testing.

Per-worker instance; read-only after construction, so no lock is needed.
``AccountSpec.__repr__`` redacts cookie values so tokens never leak into
debug logs or exception tracebacks.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AccountSpec:
    """Named account with cookies and an optional role label.

    ``role`` is embedded verbatim in the LLM system prompt — avoid PII.
    At most one account per pool may set ``default=True``; its cookies are
    injected at startup.
    """

    name: str
    cookies: list[dict]
    role: str = ''
    default: bool = False

    def __repr__(self) -> str:
        # Redact cookie values; count preserved for diagnostics.
        return (
            f'AccountSpec(name={self.name!r}, '
            f'cookies=[<{len(self.cookies)} cookie(s) redacted>], '
            f'role={self.role!r}, default={self.default})'
        )


class AccountPool:
    """Resolve cookies by priority: explicit name → default → fallback."""

    def __init__(
        self,
        accounts: list[AccountSpec] | None = None,
        fallback_cookies: list[dict] | None = None,
    ) -> None:
        accounts = list(accounts or [])
        for a in accounts:
            if not a.name or not a.name.strip():
                raise ValueError(
                    f'AccountSpec.name must be non-empty, got {a.name!r}')
        names = [a.name for a in accounts]
        if len(set(names)) != len(names):
            raise ValueError(f'duplicate account names: {names}')
        defaults = [a for a in accounts if a.default]
        if len(defaults) > 1:
            raise ValueError(
                f'multiple defaults: {[a.name for a in defaults]}')
        self._accounts = {a.name: a for a in accounts}
        self._default_name = defaults[0].name if defaults else None
        self._fallback = list(fallback_cookies or [])

    def resolve_cookies(self, name: str | None) -> list[dict] | None:
        if name:
            a = self._accounts.get(name)
            return list(a.cookies) if a else None
        if self._default_name:
            return list(self._accounts[self._default_name].cookies)
        return list(self._fallback) if self._fallback else None

    @property
    def default_name(self) -> str | None:
        return self._default_name

    @property
    def account_names(self) -> list[str]:
        return list(self._accounts)

    @property
    def has_accounts(self) -> bool:
        return bool(self._accounts)

    def get_role_summary(self) -> str:
        return '\n'.join(
            f'- {a.name}{" [default]" if a.default else ""}: '
            f'{a.role or "(no role)"}'
            for a in self._accounts.values()
        )
