"""Tests for MCP server tool registration and schema."""
import pytest

from webqa_agent.mcp_server.server import mcp

EXPECTED_TOOLS = {
    'run_test', 'get_test_status', 'get_test_report', 'cancel_test',
    'list_businesses', 'list_environments', 'list_business_files',
    'upload_business_file', 'list_executions',
}


def _get_tools():
    return {name: tool for name, tool in mcp._tool_manager._tools.items()}


def test_all_tools_registered():
    tools = _get_tools()
    assert set(tools.keys()) == EXPECTED_TOOLS


@pytest.mark.parametrize('tool_name', list(EXPECTED_TOOLS))
def test_ctx_not_in_schema(tool_name):
    tools = _get_tools()
    schema = tools[tool_name].parameters
    props = schema.get('properties', {})
    assert 'ctx' not in props, f'{tool_name} leaks ctx into schema'


def test_run_test_schema():
    schema = _get_tools()['run_test'].parameters
    props = set(schema.get('properties', {}).keys())
    required = set(schema.get('required', []))
    assert 'url' in required
    assert 'task' in required
    assert 'language' in props
    assert 'cookies' in props
    assert 'workers' in props
    assert 'test_files' in props


def test_run_test_has_annotations():
    tool = _get_tools()['run_test']
    assert tool.annotations is not None
    assert tool.annotations.openWorldHint is True
    assert tool.annotations.readOnlyHint is False


def test_query_tools_read_only():
    tools = _get_tools()
    for name in ('list_businesses', 'list_environments',
                 'list_business_files', 'list_executions',
                 'get_test_status', 'get_test_report'):
        anno = tools[name].annotations
        assert anno is not None, f'{name} missing annotations'
        assert anno.readOnlyHint is True, f'{name} should be readOnly'


def test_upload_business_file_not_read_only():
    tool = _get_tools()['upload_business_file']
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.destructiveHint is False


def test_cancel_test_destructive():
    tool = _get_tools()['cancel_test']
    assert tool.annotations.destructiveHint is True


def test_list_executions_status_enum():
    schema = _get_tools()['list_executions'].parameters
    status_prop = schema['properties'].get('status', {})
    assert 'enum' in status_prop.get('anyOf', [{}])[0] or 'enum' in status_prop, \
        'status should have enum constraint'
