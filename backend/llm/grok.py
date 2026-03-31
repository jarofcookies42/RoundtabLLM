"""
xAI Grok client (OpenAI-compatible API).

KEY CONSTRAINTS:
- Uses OpenAI SDK with custom base_url: https://api.x.ai/v1
- Temperature is a free parameter (0.0–1.0). Only model where it matters.
- Regular: grok-4-1-fast-non-reasoning (t=0.7), Overdrive: grok-4-1-fast-reasoning (t=0.9)
- Reasoning variant does internal CoT but reasoning tokens are NOT exposed via Chat Completions API.
  Only grok-3-mini returns reasoning_content. Grok 4 reasoning is hidden/encrypted (Responses API only).
"""
import openai
from typing import AsyncGenerator
from ..config import ModelConfig, GROK_API_KEY

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = openai.AsyncOpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")
    return _client


def format_history(messages: list[dict], model_key: str = "grok") -> list[dict]:
    """Same format as OpenAI. Own messages = assistant, everything else = user."""
    formatted = []
    for msg in messages:
        if msg["model"] == model_key:
            formatted.append({"role": "assistant", "content": msg["content"]})
        else:
            prefix = f"[{msg['name']}]: " if msg["role"] != "user" else "[Jack]: "
            formatted.append({"role": "user", "content": prefix + msg["content"]})
    return formatted


async def call(messages: list[dict], config: ModelConfig, system_prompt: str) -> str:
    """Call Grok API and return the full response."""
    api_messages = [{"role": "system", "content": system_prompt}] + messages

    kwargs = {
        "model": config.model_id,
        "messages": api_messages,
        "max_tokens": config.max_tokens,
    }
    if config.temperature is not None:
        kwargs["temperature"] = config.temperature

    response = await _get_client().chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


async def call_stream(
    messages: list[dict],
    config: ModelConfig,
    system_prompt: str,
) -> AsyncGenerator[str, None]:
    """Stream Grok response tokens via async generator."""
    api_messages = [{"role": "system", "content": system_prompt}] + messages

    kwargs = {
        "model": config.model_id,
        "messages": api_messages,
        "max_tokens": config.max_tokens,
        "stream": True,
    }
    if config.temperature is not None:
        kwargs["temperature"] = config.temperature

    stream = await _get_client().chat.completions.create(**kwargs)
    async for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content
