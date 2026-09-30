import asyncio
import json
from dataclasses import dataclass, field
from uuid import uuid4

from openai import AsyncOpenAI

from src.backend.core.logger import logger


@dataclass
class AnswerDiagnostics:
    request_id: str = field(default_factory=lambda: uuid4().hex)
    model: str = ""
    finish_reason: str = ""
    answer_chars: int = 0
    reasoning_chars: int = 0
    refusal_chars: int = 0
    usage: dict = field(default_factory=dict)
    error_type: str = ""
    nonblank_answer: bool = False

    @property
    def failure_reason(self):
        if self.error_type:
            return "error"
        if self.finish_reason in {"length", "content_filter"}:
            return self.finish_reason
        if self.finish_reason != "stop":
            return "incomplete"
        return "" if self.nonblank_answer else "empty"

    @property
    def succeeded(self):
        return not self.failure_reason

    def to_dict(self):
        return {
            "request_id": self.request_id,
            "model": self.model,
            "finish_reason": self.finish_reason,
            "answer_chars": self.answer_chars,
            "reasoning_chars": self.reasoning_chars,
            "refusal_chars": self.refusal_chars,
            "usage": dict(self.usage),
            "error_type": self.error_type,
            "fallback_reason": self.failure_reason,
        }

    def record(self, response, streaming):
        self.model = str(getattr(response, "model", "") or self.model)[:100]
        usage = getattr(response, "usage", None)
        if usage is not None:
            for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = getattr(usage, name, None)
                if isinstance(value, int):
                    self.usage[name] = value
            details = getattr(usage, "completion_tokens_details", None)
            reasoning_tokens = getattr(details, "reasoning_tokens", None)
            if isinstance(reasoning_tokens, int):
                self.usage["reasoning_tokens"] = reasoning_tokens
        choices = getattr(response, "choices", None)
        if not choices:
            return ""
        choice = choices[0]
        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason:
            self.finish_reason = str(finish_reason)[:40]
        message = choice.delta if streaming else choice.message
        text = getattr(message, "content", None)
        text = text if isinstance(text, str) else ""
        self.answer_chars += len(text)
        self.nonblank_answer = self.nonblank_answer or bool(text.strip())
        for name, counter in (("reasoning_content", "reasoning_chars"), ("refusal", "refusal_chars")):
            value = getattr(message, name, None)
            if isinstance(value, str):
                setattr(self, counter, getattr(self, counter) + len(value))
        return text

    def log(self):
        logger.info("Answer model diagnostics: " + json.dumps(self.to_dict(), ensure_ascii=True))


async def deepseek_answer_chunks(messages, settings, diagnostics, streaming=True):
    diagnostics.model = settings.deepseek_model
    try:
        async with asyncio.timeout(settings.answer_timeout_seconds):
            async with AsyncOpenAI(
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_api_base,
                timeout=settings.answer_timeout_seconds,
                max_retries=0,
            ) as client:
                options = {
                    "model": settings.deepseek_model,
                    "messages": messages,
                    "max_tokens": settings.answer_max_tokens,
                    "extra_body": {"thinking": {"type": "disabled"}},
                    "stream": streaming,
                }
                if streaming:
                    options["stream_options"] = {"include_usage": True}
                response = await client.chat.completions.create(**options)
                if streaming:
                    async with response:
                        async for chunk in response:
                            text = diagnostics.record(chunk, True)
                            if text:
                                yield text
                else:
                    text = diagnostics.record(response, False)
                    if text:
                        yield text
    except Exception as error:
        diagnostics.error_type = type(error).__name__
    finally:
        diagnostics.log()
