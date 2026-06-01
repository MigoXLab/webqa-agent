"""Tests for ``core.monitor.MonitorListener`` event handling.

These drive ``_dispatch_event`` directly with synthetic CDP messages — no
real browser / WebSocket — so they isolate the recording logic:

* P0 regression: a response is recorded on ``responseReceived`` even when no
  ``loadingFinished`` ever arrives (SSE / still-in-flight requests). Before the
  fix, such responses were silently dropped because they only entered the
  output on ``loadingFinished``.
* ignore-rule filtering for console + network.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from webqa_agent.executor.flash.core.monitor import MonitorListener


def _request_event(request_id: str, url: str, *, session='s1', method='GET'):
    return {
        'method': 'Network.requestWillBeSent',
        'sessionId': session,
        'params': {
            'requestId': request_id,
            'request': {'url': url, 'method': method},
        },
    }


def _response_event(request_id: str, url: str, *, session='s1',
                    status=200, mime='application/json'):
    return {
        'method': 'Network.responseReceived',
        'sessionId': session,
        'params': {
            'requestId': request_id,
            'response': {'url': url, 'status': status, 'mimeType': mime},
        },
    }


def test_sse_response_recorded_without_loading_finished():
    """SSE response with no loadingFinished must still appear in output."""
    m = MonitorListener(host='127.0.0.1', port=0)
    url = 'https://example.com/chat/completions/sse'
    m._dispatch_event(_request_event('r1', url, method='POST'))
    m._dispatch_event(_response_event('r1', url, mime='text/event-stream'))
    # Intentionally NO loadingFinished — the stream is still open.

    snap = m._snapshot()
    responses = snap['network']['responses']
    assert len(responses) == 1
    assert responses[0]['url'] == url
    assert responses[0]['status'] == 200
    assert responses[0]['body'] == '<event-stream omitted>'
    # The request is recorded too, still marked not-completed.
    requests = snap['network']['requests']
    assert len(requests) == 1
    assert requests[0]['completed'] is False


def test_pending_json_response_recorded_without_loading_finished():
    """Any in-flight response (not just SSE) survives without completion."""
    m = MonitorListener(host='127.0.0.1', port=0)
    url = 'https://example.com/api/data'
    m._dispatch_event(_request_event('r2', url))
    m._dispatch_event(_response_event('r2', url, mime='application/json'))

    responses = m._snapshot()['network']['responses']
    assert len(responses) == 1
    assert responses[0]['url'] == url
    # Body unfilled (would be fetched on loadingFinished), but the entry exists.
    assert responses[0]['body'] == ''


def test_loading_finished_marks_completed_and_keeps_single_entry():
    """A normal lifecycle yields exactly one response, marked completed."""
    m = MonitorListener(host='127.0.0.1', port=0)
    url = 'https://example.com/api/ok'
    m._dispatch_event(_request_event('r3', url))
    m._dispatch_event(_response_event('r3', url, mime='image/png'))
    m._dispatch_event({
        'method': 'Network.loadingFinished',
        'sessionId': 's1',
        'params': {'requestId': 'r3'},
    })

    snap = m._snapshot()
    assert len(snap['network']['responses']) == 1
    assert snap['network']['requests'][0]['completed'] is True
    # Non-fetchable type gets a placeholder body.
    assert 'omitted' in snap['network']['responses'][0]['body']


def test_network_ignore_rule_skips_response():
    m = MonitorListener(
        host='127.0.0.1', port=0,
        ignore_rules={'network': [{'pattern': 'analytics', 'type': 'url'}]},
    )
    m._dispatch_event(_request_event('r4', 'https://t.example.com/analytics/x'))
    m._dispatch_event(_response_event('r4', 'https://t.example.com/analytics/x'))

    assert m._snapshot()['network']['responses'] == []


def _request_with_post(request_id, url, *, session='s1', has_post=True,
                       inline=None):
    req = {'url': url, 'method': 'POST'}
    if inline is not None:
        req['postData'] = inline
    if has_post:
        req['hasPostData'] = True
    return {
        'method': 'Network.requestWillBeSent',
        'sessionId': session,
        'params': {'requestId': request_id, 'request': req},
    }


def test_omitted_post_data_is_fetched():
    """HasPostData with no inline body -> getRequestPostData backfills
    payload."""
    class FakeClient:
        def call(self, method, params, *, session_id=None, timeout=None):
            assert method == 'Network.getRequestPostData'
            assert params['requestId'] == 'r10'
            return {'postData': 'model_id=intern-s1&prompt=hi'}

    m = MonitorListener(host='127.0.0.1', port=0)
    m._client = FakeClient()
    m._body_pool = ThreadPoolExecutor(max_workers=1)
    url = 'https://example.com/chats/generate'
    m._dispatch_event(_request_with_post('r10', url))
    # response arrives before the post-data fetch completes -> still backfilled.
    m._dispatch_event(_response_event('r10', url, mime='text/event-stream'))
    m._body_pool.shutdown(wait=True)

    snap = m._snapshot()
    assert snap['network']['requests'][0]['payload'] == 'model_id=intern-s1&prompt=hi'
    # The response record's payload is backfilled too.
    assert snap['network']['responses'][0]['payload'] == 'model_id=intern-s1&prompt=hi'


def test_unfetchable_post_data_marks_payload():
    """A body-bearing request whose body can't be fetched still gets a
    marker."""
    class FakeClient:
        def call(self, *a, **k):
            raise RuntimeError('binary request body not captured')

    m = MonitorListener(host='127.0.0.1', port=0)
    m._client = FakeClient()
    m._body_pool = ThreadPoolExecutor(max_workers=1)
    m._dispatch_event(_request_with_post('r11', 'https://oss.example.com/upload'))
    m._body_pool.shutdown(wait=True)

    assert m._snapshot()['network']['requests'][0]['payload'] == '<request body omitted>'


def test_inline_post_data_not_refetched():
    """When CDP inlines postData we use it and never call
    getRequestPostData."""
    class FakeClient:
        called = False

        def call(self, *a, **k):
            FakeClient.called = True
            return {}

    m = MonitorListener(host='127.0.0.1', port=0)
    m._client = FakeClient()
    m._body_pool = ThreadPoolExecutor(max_workers=1)
    m._dispatch_event(_request_with_post('r12', 'https://x/api', inline='a=1'))
    m._body_pool.shutdown(wait=True)

    assert m._snapshot()['network']['requests'][0]['payload'] == 'a=1'
    assert FakeClient.called is False


def test_console_ignore_rule_skips_error():
    m = MonitorListener(
        host='127.0.0.1', port=0,
        ignore_rules={'console': [{'pattern': 'NoisySDK', 'match_type': 'contains'}]},
    )
    m._dispatch_event({
        'method': 'Runtime.consoleAPICalled',
        'params': {
            'type': 'error',
            'args': [{'type': 'string', 'value': 'NoisySDK failed to init'}],
        },
    })
    m._dispatch_event({
        'method': 'Runtime.consoleAPICalled',
        'params': {
            'type': 'error',
            'args': [{'type': 'string', 'value': 'RealError: boom'}],
        },
    })

    console = m._snapshot()['console']
    assert len(console) == 1
    assert 'RealError' in console[0]['msg']
