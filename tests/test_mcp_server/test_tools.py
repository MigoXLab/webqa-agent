"""Tests for MCP tool functions."""
import pytest

from webqa_agent.mcp_server.tools import testing
from webqa_agent.mcp_server.tools.files import upload_business_file
from webqa_agent.mcp_server.tools.testing import _parse_cookies


class FakeClient:
    def __init__(self, files=None):
        self.files = files or []
        self.created_params = None

    async def list_files(self, business_id):
        return self.files

    async def create_execution(self, params):
        self.created_params = params
        return {'id': 'exec-123', 'status': 'pending'}


def test_parse_cookies_valid():
    raw = [{'name': 'tok', 'value': 'abc', 'domain': '.example.com'}]
    result = _parse_cookies(raw)
    assert len(result) == 1
    assert result[0]['name'] == 'tok'


def test_parse_cookies_none():
    assert _parse_cookies(None) is None
    assert _parse_cookies([]) is None


def test_parse_cookies_not_list():
    with pytest.raises(ValueError, match='must be an array'):
        _parse_cookies('not a list')


@pytest.mark.asyncio
async def test_run_test_rejects_test_file_paths():
    client = FakeClient(files=[{'name': 'test.jpg'}])

    with pytest.raises(ValueError, match='business file names'):
        await testing.run_test(
            client,
            url='https://example.com',
            task='上传图片',
            business_id='biz-123',
            test_files=['/tmp/test.jpg'],
        )


@pytest.mark.asyncio
async def test_run_test_rejects_missing_business_files():
    client = FakeClient(files=[{'name': 'existing.jpg'}])

    with pytest.raises(ValueError, match='not found in business file pool'):
        await testing.run_test(
            client,
            url='https://example.com',
            task='上传图片',
            business_id='biz-123',
            test_files=['test.jpg'],
        )


@pytest.mark.asyncio
async def test_run_test_upload_intent_requires_available_business_files():
    client = FakeClient(files=[])

    with pytest.raises(ValueError, match='No files are available'):
        await testing.run_test(
            client,
            url='https://example.com',
            task='测试上传文件功能',
            business_id='biz-123',
        )


@pytest.mark.asyncio
async def test_run_test_upload_intent_uses_existing_business_pool():
    client = FakeClient(files=[{'name': 'test.jpg'}])

    result = await testing.run_test(
        client,
        url='https://example.com',
        task='测试上传文件功能',
        business_id='biz-123',
    )

    assert result['id'] == 'exec-123'
    assert client.created_params['business_id'] == 'biz-123'
    assert 'test_files' not in client.created_params['gen_config']


@pytest.mark.asyncio
async def test_run_test_image_upload_requires_image_file():
    client = FakeClient(files=[{'name': 'document.pdf'}])

    with pytest.raises(ValueError, match='No image files'):
        await testing.run_test(
            client,
            url='https://example.com',
            task='测试上传图片功能',
            business_id='biz-123',
        )


@pytest.mark.asyncio
async def test_run_test_image_upload_auto_whitelists_image_files():
    client = FakeClient(files=[
        {'name': 'document.pdf'},
        {'name': 'test.jpg'},
    ])

    await testing.run_test(
        client,
        url='https://example.com',
        task='测试上传图片功能',
        business_id='biz-123',
    )

    assert client.created_params['gen_config']['test_files'] == ['test.jpg']


@pytest.mark.asyncio
async def test_upload_business_file_requires_absolute_path():
    client = FakeClient()

    with pytest.raises(ValueError, match='absolute path'):
        await upload_business_file(client, 'biz-123', 'test.jpg')
