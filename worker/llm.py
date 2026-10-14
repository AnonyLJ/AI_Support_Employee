"""LLM adapter: one method, complete(messages, tools) -> LLMReply.

Only this file knows about OpenAI. Switching provider (or using a scripted
fake model in tests) means writing another class with the same method.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class LLMError(Exception):
    """The model could not be called (bad key, network, rate limit after retries, ...)."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON text, as produced by the model


@dataclass
class LLMReply:
    text: str | None
    tool_calls: list[ToolCall]
    message: dict                      # the assistant message to append to the conversation
    usage: dict = field(default_factory=dict)


class OpenAIChat:
    def __init__(self, model: str, reasoning_effort: str | None = None):
        try:
            import openai
        except ImportError as exc:
            raise LLMError("The 'openai' package is not installed (pip install -r requirements.txt)") from exc
        self._openai = openai
        try:
            # The SDK itself retries connection errors, 429 and 5xx with backoff.
            self.client = openai.OpenAI(max_retries=4, timeout=120)
        except openai.OpenAIError as exc:  # e.g. OPENAI_API_KEY not set
            raise LLMError(str(exc)) from exc
        self.model = model
        self.reasoning_effort = reasoning_effort

    def complete(self, messages: list[dict], tools: list[dict]) -> LLMReply:
        openai = self._openai
        kwargs = {"model": self.model, "messages": messages, "tools": tools}
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        try:
            response = self.client.chat.completions.create(**kwargs)
        except openai.AuthenticationError as exc:
            raise LLMError("OpenAI rejected the API key. Set a valid OPENAI_API_KEY.") from exc
        except openai.NotFoundError as exc:
            raise LLMError(f"Model '{self.model}' is not available to this API key ({exc.message})") from exc
        except openai.RateLimitError as exc:
            raise LLMError(f"OpenAI rate limit or quota exceeded: {exc.message}") from exc
        except openai.APIConnectionError as exc:
            raise LLMError("Could not reach the OpenAI API (network problem).") from exc
        except openai.APIStatusError as exc:
            raise LLMError(f"OpenAI API error {exc.status_code}: {exc.message}") from exc

        msg = response.choices[0].message
        calls = [ToolCall(tc.id, tc.function.name, tc.function.arguments or "{}")
                 for tc in (msg.tool_calls or []) if tc.type == "function"]
        message: dict = {"role": "assistant", "content": msg.content}
        if calls:
            message["tool_calls"] = [{"id": c.id, "type": "function",
                                      "function": {"name": c.name, "arguments": c.arguments}} for c in calls]
        usage = {}
        if response.usage:
            usage = {"input": response.usage.prompt_tokens, "output": response.usage.completion_tokens}
        return LLMReply(text=msg.content or msg.refusal, tool_calls=calls, message=message, usage=usage)
