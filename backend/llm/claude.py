"""
Anthropic Claude client — handles both Sonnet 4.6 (Regular) and Opus 4.6 (Overdrive).

KEY CONSTRAINTS:
- When thinking is enabled, DO NOT pass temperature or top_k — API will reject.
- Response contains both "thinking" and "text" content blocks — only return "text" blocks.
- Messages must alternate user/assistant. Merge consecutive same-role messages.
- Thinking blocks from prior turns are auto-ignored by the API (don't need to strip them).
- For adaptive thinking (Overdrive), the model decides its own thinking budget per request.
"""
import anthropic
from typing import AsyncGenerator
from ..config import ModelConfig, ANTHROPIC_API_KEY


class ThinkingStream:
    """Async iterable wrapper that captures thinking blocks while yielding text deltas."""

    def __init__(self, aiter):
        self._aiter = aiter
        self.thinking_content: str | None = None
        self._thinking_parts: list[str] = []

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self._aiter.__anext__()

    def _finalize(self):
        self.thinking_content = "\n".join(self._thinking_parts) if self._thinking_parts else None

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def format_history(messages: list[dict], model_key: str = "claude") -> list[dict]:
    """
    Convert roundtable message history to Claude's alternating user/assistant format.

    Rules:
    - Claude's own prior messages → role: "assistant"
    - Everything else (user + other models) → role: "user" with [Name]: prefix
    - Consecutive same-role messages must be merged with newline separator
    """
    raw = []
    for msg in messages:
        if msg["model"] == model_key:
            raw.append({"role": "assistant", "content": msg["content"]})
        else:
            prefix = f"[{msg['name']}]: "
            raw.append({"role": "user", "content": prefix + msg["content"]})

    # Merge consecutive same-role messages
    merged = []
    for entry in raw:
        if merged and merged[-1]["role"] == entry["role"]:
            merged[-1]["content"] += "\n\n" + entry["content"]
        else:
            merged.append(dict(entry))

    return merged


def resolve_thinking_config(config: ModelConfig) -> tuple[dict | None, str | None]:
    """
    Resolves and returns the thinking dictionary and effort parameter for the Claude API.
    Handles compatibility adjustments for models (like Opus 4.7) that only support adaptive thinking.
    """
    if not config.thinking:
        return None, None

    thinking = dict(config.thinking)
    effort = config.effort

    # If the model is an Opus model, it only supports "adaptive" thinking type.
    is_opus = "opus" in config.model_id.lower()
    
    if is_opus:
        if thinking.get("type") != "adaptive":
            thinking["type"] = "adaptive"
        # Opus doesn't support budget_tokens
        if "budget_tokens" in thinking:
            del thinking["budget_tokens"]
        # Ensure effort is set (defaults to "max" if not specified)
        if not effort:
            effort = "max"
            
    return thinking, effort


async def call(
    messages: list[dict],
    config: ModelConfig,
    system_prompt: str,
) -> str:
    """
    Call Claude API and return the text response (not thinking blocks).
    """
    kwargs = {
        "model": config.model_id,
        "max_tokens": config.max_tokens,
        "system": system_prompt,
        "messages": messages,
    }
    # When thinking is enabled, do NOT pass temperature
    thinking, effort = resolve_thinking_config(config)
    if thinking:
        kwargs["thinking"] = thinking
        if effort:
            kwargs["output_config"] = {"effort": effort}
    elif config.temperature is not None:
        kwargs["temperature"] = config.temperature

    response = await _get_client().messages.create(**kwargs)

    # Extract only text blocks (skip thinking blocks)
    parts = []
    for block in response.content:
        if block.type == "text":
            parts.append(block.text)
    return "\n".join(parts)


def call_stream(
    messages: list[dict],
    config: ModelConfig,
    system_prompt: str,
) -> ThinkingStream:
    """
    Stream Claude response tokens. Returns a ThinkingStream that yields text deltas
    and accumulates thinking content accessible via .thinking_content after iteration.
    """
    kwargs = {
        "model": config.model_id,
        "max_tokens": config.max_tokens,
        "system": system_prompt,
        "messages": messages,
    }
    thinking, effort = resolve_thinking_config(config)
    if thinking:
        kwargs["thinking"] = thinking
        if effort:
            kwargs["output_config"] = {"effort": effort}
    elif config.temperature is not None:
        kwargs["temperature"] = config.temperature

    async def _generate():
        async with _get_client().messages.stream(**kwargs) as stream:
            async for event in stream:
                if event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        yield {"type": "text", "text": event.delta.text}
                    elif event.delta.type == "thinking_delta":
                        wrapper._thinking_parts.append(event.delta.thinking)
                        yield {"type": "thinking", "text": event.delta.thinking}
        wrapper._finalize()

    wrapper = ThinkingStream(_generate())
    return wrapper
