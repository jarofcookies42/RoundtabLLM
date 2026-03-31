"""
OpenAI GPT-5.4 client.

KEY CONSTRAINTS:
- Temperature is LOCKED at 1. Do not pass any other value — API returns 400 error.
- Safest approach: don't pass temperature at all.
- reasoning_effort controls thinking depth: "none" (default, fastest), "low", "medium", "high", "xhigh"
- Reasoning tokens are HIDDEN — billed but not visible in Chat Completions API response.
  "high" can add 2000+ hidden tokens. Summaries available via Responses API only (not used here).
- verbosity controls output length: "low", "medium", "high"
- Uses standard OpenAI chat completions format.
- thinking_content will always be None for GPT-5.4 via this API.
"""
import openai
from typing import AsyncGenerator
from ..config import ModelConfig, OPENAI_API_KEY

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
    return _client


def format_history(messages: list[dict], model_key: str = "gpt") -> list[dict]:
    """
    Convert roundtable history to OpenAI format.

    Rules:
    - GPT's own prior messages → role: "assistant"
    - Everything else → role: "user" with [Name]: prefix
    - System message is prepended separately in call/call_stream
    """
    formatted = []
    for msg in messages:
        if msg["model"] == model_key:
            formatted.append({"role": "assistant", "content": msg["content"]})
        else:
            prefix = f"[{msg['name']}]: " if msg["role"] != "user" else "[Jack]: "
            formatted.append({"role": "user", "content": prefix + msg["content"]})
    return formatted


async def call(messages: list[dict], config: ModelConfig, system_prompt: str) -> str:
    """Call GPT-5.4 and return the response. Do NOT pass temperature."""
    api_messages = [{"role": "system", "content": system_prompt}] + messages

    kwargs = {
        "model": config.model_id,
        "messages": api_messages,
        "max_completion_tokens": config.max_tokens,
        # DO NOT pass temperature — only default (1) is supported
    }
    if config.reasoning_effort and config.reasoning_effort != "none":
        kwargs["reasoning_effort"] = config.reasoning_effort

    response = await _get_client().chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


async def call_stream(
    messages: list[dict],
    config: ModelConfig,
    system_prompt: str,
) -> AsyncGenerator[str, None]:
    """Stream GPT response tokens."""
    api_messages = [{"role": "system", "content": system_prompt}] + messages

    kwargs = {
        "model": config.model_id,
        "messages": api_messages,
        "max_completion_tokens": config.max_tokens,
        "stream": True,
    }
    if config.reasoning_effort and config.reasoning_effort != "none":
        kwargs["reasoning_effort"] = config.reasoning_effort

    stream = await _get_client().chat.completions.create(**kwargs)
    async for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content
