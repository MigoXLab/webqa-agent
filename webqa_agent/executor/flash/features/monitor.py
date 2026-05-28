"""Wrap a Flash monitor payload into the canonical report schema.

The CDP listener (``core/monitor.py``) only knows about ``monitoring_data``
— the inner ``{console, network}`` dict. The case-level metadata
(``sub_test_id``, ``name``, ``safe_name``, ``corresponding_file``,
``timestamp``) is owned by the caller, because only the executor knows the
case index, the original task text, and the report directory layout.

These helpers bridge the two so the on-disk JSON matches the schema agreed
with the user.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

_SAFE_NAME_INVALID_RE = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def safe_case_name(name: str) -> str:
    """Filesystem-safe version of a case display name.

    Strips path-illegal characters but keeps Unicode (the agreed schema
    shows Chinese characters survive unchanged).
    """
    cleaned = _SAFE_NAME_INVALID_RE.sub('', name or '').strip()
    return cleaned or 'case'


def _empty_monitoring_data() -> dict:
    return {
        'console': [],
        'network': {
            'requests': [],
            'responses': [],
            'failed_requests': [],
        },
    }


def wrap_monitor_payload(
    monitoring_data: dict | None,
    *,
    sub_test_id: str,
    name: str,
    display_name: str | None = None,
    safe_name: str | None = None,
    corresponding_file: str | None = None,
    timestamp: str | None = None,
) -> dict:
    """Wrap raw ``monitoring_data`` into the case-level report entry.

    Returns a single-key dict ``{<sub_test_id>_<safe_name>_monitor: <entry>}``.
    The entry shape matches the agreed schema: ``sub_test_id``, ``name``,
    ``display_name``, ``safe_name``, ``corresponding_file``, ``monitoring_data``,
    ``timestamp``.
    """
    safe = safe_name or safe_case_name(name)
    disp = display_name or name
    corresp = corresponding_file or f'{sub_test_id}_{safe}_data.json'
    ts = timestamp or datetime.now().isoformat()
    entry = {
        'sub_test_id': sub_test_id,
        'name': name,
        'display_name': disp,
        'safe_name': safe,
        'corresponding_file': corresp,
        'monitoring_data': monitoring_data or _empty_monitoring_data(),
        'timestamp': ts,
    }
    return {f'{sub_test_id}_{safe}_monitor': entry}


def dump_monitor_json(
    payload: dict, *, report_dir: str | Path, file_name: str,
) -> Path:
    """Write a wrapped monitor payload to ``<report_dir>/<file_name>``.

    Returns the absolute path written.
    """
    out_path = Path(report_dir) / file_name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    return out_path.resolve()
