from __future__ import annotations

from webqa_agent.executor.flash.core.engine import Engine
from webqa_agent.executor.flash.core.llm import LLMMessage, LLMUsage
from webqa_agent.executor.flash.core.permissions import PermissionChecker


class _FakeStream:
    def __init__(self) -> None:
        self.text_stream = iter(['hello'])

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def close(self) -> None:
        return None

    def get_final_message(self) -> LLMMessage:
        return LLMMessage(
            content=[{'type': 'text', 'text': 'done'}],
            usage=LLMUsage(input_tokens=12, output_tokens=4),
        )


class _FakeClient:
    def __init__(self) -> None:
        self.last_request = {}

    def stream_messages(self, **kwargs):
        self.last_request = kwargs
        return _FakeStream()

    def is_authentication_error(self, _exc: Exception) -> bool:
        return False

    def is_api_error(self, _exc: Exception) -> bool:
        return False

    def is_retryable_error(self, _exc: Exception) -> bool:
        return False

    def error_message(self, exc: Exception) -> str:
        return str(exc)


def test_engine_emits_llm_dataflow_event_with_real_request_snapshot():
    engine = Engine(
        tools=[],
        system_prompt='system prompt',
        permission_checker=PermissionChecker(),
        provider='openai',
        model='gpt-4o',
        api_key='fake-key',
    )
    fake_client = _FakeClient()
    engine._client = fake_client

    events = list(engine.submit('user task'))
    dataflow_events = [
        event[1] for event in events
        if event[0] == 'data_flow_event'
    ]

    assert len(dataflow_events) == 1
    payload = dataflow_events[0]['payload']
    assert dataflow_events[0]['event_type'] == 'cc_mini_llm_call'
    assert payload['call_id'] == 'llm-1-1'
    assert payload['duration_seconds'] >= 0
    assert payload['token_usage']['input_tokens'] == 12
    assert payload['token_usage']['output_tokens'] == 4
    assert payload['token_usage']['total_tokens'] == 16
    assert payload['request']['system'] == 'system prompt'
    assert payload['request']['messages'][0] == {
        'role': 'user',
        'content': 'user task',
    }
