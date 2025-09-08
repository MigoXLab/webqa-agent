import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any


I18N_DIR = Path(__file__).resolve().parents[1] / 'static' / 'i18n'


@lru_cache(maxsize=8)
def _load_lang(lang: str) -> dict[str, Any]:
    try:
        file_path = I18N_DIR / f'{lang}.json'
        if not file_path.exists():
            # fallback to zh-CN if specific lang not found
            logging.warning(f'i18n file not found for {lang}, fallback to zh-CN')
            file_path = I18N_DIR / 'zh-CN.json'
        return json.loads(file_path.read_text(encoding='utf-8'))
    except Exception as e:
        logging.error(f'Failed to load i18n file for {lang}: {e}')
        return {}


def t(lang: str, key: str, default: str | None = None) -> str:
    """Translate a namespaced key like 'aggregator.summary_and_advice'."""
    data = _load_lang(lang)
    node: Any = data
    for part in key.split('.'):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return default if default is not None else key
    return node if isinstance(node, str) else default if default is not None else key


def get_lang_data(lang: str) -> dict[str, Any]:
    """Return the full language dict (read-only)."""
    return _load_lang(lang).copy()


