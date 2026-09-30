import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.backend.ingestion.answer_model import AnswerDiagnostics, deepseek_answer_chunks


class FakeStream:
    def __init__(self, chunks):
        self.chunks = chunks

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for chunk in self.chunks:
            yield chunk


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create)
        )
        self.create_kwargs = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def create(self, **kwargs):
        self.create_kwargs = kwargs
        return self.response


class FakeClientFactory:
    def __init__(self, response):
        self.client = FakeClient(response)
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self.client


@pytest.fixture
def answer_settings():
    return SimpleNamespace(
        deepseek_api_key="test-key",
        deepseek_api_base="https://example.invalid",
        deepseek_model="deepseek-v4-flash",
        answer_max_tokens=4096,
        answer_timeout_seconds=90,
    )


def response_chunk(content=None, finish_reason=None, usage=None, **delta_fields):
    return SimpleNamespace(
        model="deepseek-v4-flash",
        usage=usage,
        choices=[SimpleNamespace(
            finish_reason=finish_reason,
            delta=SimpleNamespace(content=content, **delta_fields),
        )],
    )


@pytest.mark.asyncio
async def test_streaming_request_disables_thinking_and_accepts_usage_only_chunk(answer_settings):
    usage = SimpleNamespace(prompt_tokens=12, completion_tokens=8, total_tokens=20)
    response = FakeStream([
        response_chunk("答", usage=usage),
        SimpleNamespace(model="deepseek-v4-flash", usage=usage, choices=[]),
        response_chunk(None, finish_reason="stop", usage=usage),
    ])
    factory = FakeClientFactory(response)
    diagnostics = AnswerDiagnostics()

    with patch("src.backend.ingestion.answer_model.AsyncOpenAI", factory):
        chunks = [
            text async for text in deepseek_answer_chunks(
                [{"role": "user", "content": "问题"}],
                answer_settings,
                diagnostics,
                streaming=True,
            )
        ]

    assert chunks == ["答"]
    assert factory.kwargs == {
        "api_key": "test-key",
        "base_url": "https://example.invalid",
        "timeout": 90,
        "max_retries": 0,
    }
    assert factory.client.create_kwargs["max_tokens"] == 4096
    assert factory.client.create_kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert factory.client.create_kwargs["stream_options"] == {"include_usage": True}
    assert diagnostics.finish_reason == "stop"
    assert diagnostics.usage == {
        "prompt_tokens": 12,
        "completion_tokens": 8,
        "total_tokens": 20,
    }
    assert diagnostics.succeeded


@pytest.mark.asyncio
async def test_non_streaming_response_records_content_and_usage(answer_settings):
    usage = SimpleNamespace(prompt_tokens=4, completion_tokens=6, total_tokens=10)
    response = SimpleNamespace(
        model="deepseek-v4-flash",
        usage=usage,
        choices=[SimpleNamespace(
            finish_reason="stop",
            message=SimpleNamespace(
                content="完整答案",
                reasoning_content="内部推理",
                refusal=None,
            ),
        )],
    )
    factory = FakeClientFactory(response)
    diagnostics = AnswerDiagnostics()

    with patch("src.backend.ingestion.answer_model.AsyncOpenAI", factory):
        chunks = [
            text async for text in deepseek_answer_chunks(
                [{"role": "user", "content": "问题"}],
                answer_settings,
                diagnostics,
                streaming=False,
            )
        ]

    assert chunks == ["完整答案"]
    assert diagnostics.answer_chars == 4
    assert diagnostics.reasoning_chars == 4
    assert diagnostics.finish_reason == "stop"
    assert diagnostics.to_dict()["fallback_reason"] == ""


def test_diagnostics_classifies_truncated_and_empty_responses():
    diagnostics = AnswerDiagnostics(finish_reason="length", nonblank_answer=True)
    assert diagnostics.failure_reason == "length"

    diagnostics = AnswerDiagnostics(finish_reason="stop")
    assert diagnostics.failure_reason == "empty"

    diagnostics = AnswerDiagnostics(finish_reason="stop", nonblank_answer=True)
    assert diagnostics.succeeded


@pytest.mark.asyncio
async def test_api_exception_is_exposed_in_diagnostics(answer_settings):
    class FailingClient(FakeClient):
        async def create(self, **kwargs):
            raise TimeoutError("timed out")

    factory = FakeClientFactory(None)
    factory.client = FailingClient(None)
    diagnostics = AnswerDiagnostics()

    with patch("src.backend.ingestion.answer_model.AsyncOpenAI", factory):
        chunks = [
            text async for text in deepseek_answer_chunks(
                [{"role": "user", "content": "问题"}],
                answer_settings,
                diagnostics,
                streaming=False,
            )
        ]

    assert chunks == []
    assert diagnostics.error_type == "TimeoutError"
    assert diagnostics.failure_reason == "error"
