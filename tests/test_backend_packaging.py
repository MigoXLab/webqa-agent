"""Guards for K8s backend image layout (backend-only, no webqa_agent)."""
from __future__ import annotations

import ast
from pathlib import Path

BACKEND_APP_ROOT = Path(__file__).resolve().parents[1] / 'backend' / 'app'


def _collect_webqa_agent_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name == 'webqa_agent' or name.startswith('webqa_agent.'):
                    hits.append(f'{path.relative_to(BACKEND_APP_ROOT.parent)}:{node.lineno}')
        elif isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module
            if mod == 'webqa_agent' or mod.startswith('webqa_agent.'):
                hits.append(f'{path.relative_to(BACKEND_APP_ROOT.parent)}:{node.lineno}')
    return hits


def test_backend_app_must_not_import_webqa_agent():
    """Webqa-be image has no webqa_agent package; Job image does."""
    violations: list[str] = []
    for path in sorted(BACKEND_APP_ROOT.rglob('*.py')):
        violations.extend(_collect_webqa_agent_imports(path))
    assert not violations, (
        'backend/app must not import webqa_agent (breaks webqa-be K8s image):\n'
        + '\n'.join(violations)
    )
