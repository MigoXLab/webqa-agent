"""Unit tests for webqa_agent.utils.schema_utils.

Covers:
- flatten_nullable_anyof: in-place JSON schema transformation
- LLMCompatibleSchema: Pydantic base class with proxy-compatible schema output
"""

import copy
import json
from typing import Any, Optional, Type, Union

import pytest
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, Field

from webqa_agent.utils.schema_utils import (LLMCompatibleSchema,
                                            flatten_nullable_anyof)

# ── flatten_nullable_anyof ────────────────────────────────────────────────────


class TestFlattenNullableAnyofSimpleTypes:
    """Optional[T] with a single primitive type should flatten to type +
    nullable."""

    @pytest.mark.parametrize(
        'pydantic_type, expected_type',
        [
            (Optional[str], 'string'),
            (Optional[int], 'integer'),
            (Optional[float], 'number'),
            (Optional[bool], 'boolean'),
        ],
    )
    def test_optional_primitive_flattened(self, pydantic_type, expected_type):
        schema = {
            'properties': {
                'field': {
                    'anyOf': [{'type': expected_type}, {'type': 'null'}],
                    'default': None,
                }
            }
        }
        flatten_nullable_anyof(schema)
        prop = schema['properties']['field']
        assert 'anyOf' not in prop
        assert prop['type'] == expected_type
        assert prop['nullable'] is True

    def test_null_first_order_still_flattens(self):
        """Null appearing before the real type should still be flattened."""
        schema = {
            'properties': {
                'field': {'anyOf': [{'type': 'null'}, {'type': 'string'}]}
            }
        }
        flatten_nullable_anyof(schema)
        prop = schema['properties']['field']
        assert 'anyOf' not in prop
        assert prop['type'] == 'string'
        assert prop['nullable'] is True


class TestFlattenNullableAnyofPreservesExtra:
    """Extra attributes on the property must survive the transformation."""

    def test_preserves_description(self):
        schema = {
            'properties': {
                'field': {
                    'anyOf': [{'type': 'string'}, {'type': 'null'}],
                    'description': 'my description',
                    'default': None,
                    'title': 'Field',
                }
            }
        }
        flatten_nullable_anyof(schema)
        prop = schema['properties']['field']
        assert prop['description'] == 'my description'
        assert prop['default'] is None
        assert prop['title'] == 'Field'
        assert prop['type'] == 'string'
        assert prop['nullable'] is True


class TestFlattenNullableAnyofNoChange:
    """Schemas that should NOT be modified."""

    def test_plain_type_unchanged(self):
        schema = {'properties': {'field': {'type': 'string'}}}
        original = {'properties': {'field': {'type': 'string'}}}
        flatten_nullable_anyof(schema)
        assert schema == original

    def test_union_multiple_non_null_unchanged(self):
        """Union[str, int, None] has two non-null types — should not
        flatten."""
        schema = {
            'properties': {
                'field': {
                    'anyOf': [
                        {'type': 'string'},
                        {'type': 'integer'},
                        {'type': 'null'},
                    ]
                }
            }
        }
        original = copy.deepcopy(schema)
        flatten_nullable_anyof(schema)
        assert schema == original

    def test_union_no_null_unchanged(self):
        """Union[str, int] without null — should not flatten."""
        schema = {
            'properties': {
                'field': {'anyOf': [{'type': 'string'}, {'type': 'integer'}]}
            }
        }
        original = copy.deepcopy(schema)
        flatten_nullable_anyof(schema)
        assert schema == original

    def test_anyof_null_only_unchanged(self):
        """AnyOf containing only null — edge case, should not flatten."""
        schema = {'properties': {'field': {'anyOf': [{'type': 'null'}]}}}
        original = copy.deepcopy(schema)
        flatten_nullable_anyof(schema)
        assert schema == original

    def test_empty_schema_unchanged(self):
        schema: dict = {}
        flatten_nullable_anyof(schema)
        assert schema == {}

    def test_no_properties_key_unchanged(self):
        schema = {'title': 'Foo', 'type': 'object'}
        flatten_nullable_anyof(schema)
        assert schema == {'title': 'Foo', 'type': 'object'}


class TestFlattenNullableAnyofRecursion:
    """$defs sub-schemas should be recursively fixed."""

    def test_defs_sub_schema_flattened(self):
        schema = {
            'properties': {'top': {'type': 'string'}},
            '$defs': {
                'Nested': {
                    'properties': {
                        'inner': {
                            'anyOf': [{'type': 'string'}, {'type': 'null'}]
                        }
                    }
                }
            },
        }
        flatten_nullable_anyof(schema)
        inner = schema['$defs']['Nested']['properties']['inner']
        assert 'anyOf' not in inner
        assert inner['type'] == 'string'
        assert inner['nullable'] is True

    def test_returns_none(self):
        """Function must modify in-place and return None."""
        schema = {
            'properties': {
                'f': {'anyOf': [{'type': 'string'}, {'type': 'null'}]}
            }
        }
        assert flatten_nullable_anyof(schema) is None


# ── LLMCompatibleSchema ───────────────────────────────────────────────────────

class TestLLMCompatibleSchemaOptionalFields:
    """Optional fields in LLMCompatibleSchema must not generate anyOf."""

    def test_optional_str_no_anyof(self):
        class Schema(LLMCompatibleSchema):
            target: Optional[str] = None

        schema = Schema.model_json_schema()
        prop = schema['properties']['target']
        assert 'anyOf' not in prop
        assert prop['type'] == 'string'
        assert prop['nullable'] is True

    def test_multiple_optional_fields_all_flattened(self):
        class Schema(LLMCompatibleSchema):
            a: Optional[str] = None
            b: Optional[int] = None
            c: Optional[float] = None

        schema = Schema.model_json_schema()
        assert 'anyOf' not in json.dumps(schema)
        for key in ('a', 'b', 'c'):
            assert 'type' in schema['properties'][key]
            assert schema['properties'][key]['nullable'] is True

    def test_required_field_unchanged(self):
        class Schema(LLMCompatibleSchema):
            name: str

        schema = Schema.model_json_schema()
        prop = schema['properties']['name']
        assert prop['type'] == 'string'
        assert 'anyOf' not in prop
        assert 'nullable' not in prop

    def test_mixed_required_and_optional(self):
        class Schema(LLMCompatibleSchema):
            action: str
            target: Optional[str] = None

        schema = Schema.model_json_schema()
        assert schema['properties']['action']['type'] == 'string'
        assert 'nullable' not in schema['properties']['action']
        assert schema['properties']['target']['type'] == 'string'
        assert schema['properties']['target']['nullable'] is True

    def test_complex_union_not_flattened(self):
        """Union[str, int] without null must still use anyOf."""
        class Schema(LLMCompatibleSchema):
            value: Union[str, int]

        schema = Schema.model_json_schema()
        prop = schema['properties']['value']
        assert 'anyOf' in prop

    def test_model_json_schema_returns_dict(self):
        class Schema(LLMCompatibleSchema):
            x: str

        result = Schema.model_json_schema()
        assert isinstance(result, dict)

    def test_no_anyof_anywhere_in_schema(self):
        """Full tree must be free of nullable anyOf patterns."""
        class Schema(LLMCompatibleSchema):
            action: str
            target: Optional[str] = None
            value: Optional[str] = Field(default=None, description='some value')
            count: Optional[int] = None

        schema = Schema.model_json_schema()
        assert '"anyOf"' not in json.dumps(schema)


class TestPlainBaseModelComparison:
    """Contrast: plain BaseModel still produces anyOf (baseline behaviour)."""

    def test_plain_basemodel_has_anyof(self):
        class PlainSchema(BaseModel):
            target: Optional[str] = None

        prop = PlainSchema.model_json_schema()['properties']['target']
        assert 'anyOf' in prop

    def test_llm_compatible_differs_from_plain(self):
        class Plain(BaseModel):
            target: Optional[str] = None

        class Compat(LLMCompatibleSchema):
            target: Optional[str] = None

        plain_prop = Plain.model_json_schema()['properties']['target']
        compat_prop = Compat.model_json_schema()['properties']['target']
        assert 'anyOf' in plain_prop
        assert 'anyOf' not in compat_prop


# ── LangChain tool_call_schema integration ────────────────────────────────────

class TestToolCallSchemaIntegration:
    """Verify that the tool_call_schema override survives LangChain's
    conversion.

    LangChain's BaseTool.tool_call_schema normally wraps args_schema via
    _create_subset_model(), producing a fresh BaseModel that loses our fixes.
    The override must return model_json_schema() directly so that
    convert_to_openai_tool() sends a clean schema to the API proxy.
    """

    def _make_tool(self, schema_cls: type) -> BaseTool:
        class _StubTool(BaseTool):
            name: str = 'test_tool'
            description: str = 'test'
            args_schema: Type[BaseModel] = schema_cls

            def _run(self, **kw: Any) -> str:
                return ''

            async def _arun(self, **kw: Any) -> str:
                return ''

            @property
            def tool_call_schema(self) -> dict[str, Any]:  # mirrors UITool/UIAssertTool
                return self.args_schema.model_json_schema()

        return _StubTool()

    def test_convert_to_openai_tool_no_anyof(self):
        """End-to-end: convert_to_openai_tool must not emit anyOf for Optional fields."""
        class Schema(LLMCompatibleSchema):
            action: str
            target: Optional[str] = None
            value: Optional[str] = None

        openai_tool = convert_to_openai_tool(self._make_tool(Schema))
        assert '"anyOf"' not in json.dumps(openai_tool)

    def test_convert_to_openai_tool_nullable_preserved(self):
        """nullable: true must survive the convert_to_openai_tool round-trip."""
        class Schema(LLMCompatibleSchema):
            action: str
            target: Optional[str] = None

        props = convert_to_openai_tool(self._make_tool(Schema))['function']['parameters']['properties']
        assert props['target']['type'] == 'string'
        assert props['target']['nullable'] is True
        assert 'anyOf' not in props['action']
