"""Schema utilities for LLM API proxy compatibility.

The API proxy enforces strict function-calling schema validation (Gemini-style):
every parameter must have an explicit top-level ``type`` field.  Pydantic V2
generates::

    {"anyOf": [{"type": "string"}, {"type": "null"}]}

for ``Optional[T]`` fields, which lacks a top-level ``type`` and is rejected
with HTTP 400 — intermittently but reproducibly — for all models routed
through the proxy (Gemini, GPT, etc.).

This module provides :class:`LLMCompatibleSchema` — a drop-in replacement for
``pydantic.BaseModel`` that fixes the schema at generation time by transforming
``anyOf`` nullable patterns into ``{"type": T, "nullable": true}``.

Usage::

    from webqa_agent.utils.schema_utils import LLMCompatibleSchema

    class MyToolSchema(LLMCompatibleSchema):
        name: str
        target: Optional[str] = None   # → {"type": "string", "nullable": true}
"""

from typing import Any

from pydantic import BaseModel


def flatten_nullable_anyof(schema: dict[str, Any]) -> None:
    """Recursively fix ``anyOf`` nullable patterns in a JSON schema dict.

    Transforms ``anyOf: [{"type": T}, {"type": "null"}]`` into
    ``{"type": T, "nullable": true}`` in all ``properties`` entries.

    Only simple ``Optional[T]`` shapes (exactly one non-null primitive type
    carrying its own ``"type"`` key) are flattened; complex ``Union`` types
    with multiple non-null members are left untouched.

    Modifies *schema* in-place.
    """
    for prop in schema.get('properties', {}).values():
        _fix_nullable_prop(prop)

    # Recurse into referenced sub-schemas ($defs / definitions)
    for sub in schema.get('$defs', {}).values():
        flatten_nullable_anyof(sub)


def _fix_nullable_prop(prop: dict[str, Any]) -> None:
    """Flatten a single property schema if it matches the anyOf nullable
    pattern."""
    if 'anyOf' not in prop:
        return

    any_of: list[dict[str, Any]] = prop['anyOf']
    non_null = [s for s in any_of if s.get('type') != 'null']
    has_null = len(non_null) < len(any_of)

    # Only flatten: exactly one non-null member with a plain primitive "type"
    if has_null and len(non_null) == 1 and 'type' in non_null[0]:
        prop.pop('anyOf')
        prop.update(non_null[0])
        prop['nullable'] = True


class LLMCompatibleSchema(BaseModel):
    """Pydantic ``BaseModel`` with LLM-proxy-compatible JSON schema output.

    Overrides :meth:`model_json_schema` to transform ``Optional[T]``
    ``anyOf`` patterns into ``{"type": T, "nullable": true}``.

    Required because the API proxy enforces Gemini-style strict schema
    validation for all models: each function parameter must carry an
    explicit top-level ``type`` field.  Without this fix, any ``Optional``
    parameter causes intermittent HTTP 400 errors.

    All tool argument schemas should inherit from this class.
    """

    @classmethod
    def model_json_schema(cls, **kwargs: Any) -> dict[str, Any]:
        schema = super().model_json_schema(**kwargs)
        flatten_nullable_anyof(schema)
        return schema
