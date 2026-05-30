"""
Google Gemini 3.1 Pro client.

KEY CONSTRAINTS:
- Temperature MUST be 1.0. Below 1.0 causes looping and degraded reasoning. Google explicitly warns.
- thinking_level: "low" | "medium" | "high". "high" activates Deep Think Mini.
- Do NOT use thinking_level with the legacy thinking_budget param — causes 400 error.
- System instructions go in system_instruction param, NOT in contents.
- Uses "user"/"model" roles (not "assistant").
- Thought signatures may appear in responses — preserve for multi-turn but don't display.
- top_p: 0.95 recommended default.
"""
from typing import AsyncGenerator
from ..config import ModelConfig, GOOGLE_AI_API_KEY

from google import genai
from google.genai import types

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=GOOGLE_AI_API_KEY)
    return _client


def format_history(messages: list[dict], model_key: str = "gemini") -> list[dict]:
    """
    Convert roundtable history to Gemini contents format.

    Rules:
    - Gemini's own prior messages → role: "model"
    - Everything else → role: "user" with [Name]: prefix
    - System instruction is separate (not in contents)
    """
    formatted = []
    for msg in messages:
        if msg["model"] == model_key:
            formatted.append({"role": "model", "parts": [{"text": msg["content"]}]})
        else:
            prefix = f"[{msg['name']}]: " if msg["role"] != "user" else "[Jack]: "
            formatted.append({"role": "user", "parts": [{"text": prefix + msg["content"]}]})

    # Gemini also requires alternating roles — merge consecutive same-role
    merged = []
    for entry in formatted:
        if merged and merged[-1]["role"] == entry["role"]:
            merged[-1]["parts"].extend(entry["parts"])
        else:
            merged.append(dict(entry))

    return merged


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
        self.thinking_content = "".join(self._thinking_parts) if self._thinking_parts else None


async def call(messages: list[dict], config: ModelConfig, system_prompt: str) -> str:
    """Call Gemini and return the full text response (excluding thoughts)."""
    client = _get_client()
    gen_config = _build_gen_config(config)
    if config.thinking_level is not None:
        gen_config["include_thoughts"] = True

    response = await client.aio.models.generate_content(
        model=config.model_id,
        contents=messages,
        config=_build_generate_config(gen_config, system_prompt),
    )
    # Extract only final text parts (exclude thoughts)
    parts = []
    if response.candidates:
        for candidate in response.candidates:
            if candidate.content and candidate.content.parts:
                for part in candidate.content.parts:
                    if hasattr(part, "text") and part.text and not getattr(part, "thought", False):
                        parts.append(part.text)
    return "".join(parts)


def call_stream(
    messages: list[dict],
    config: ModelConfig,
    system_prompt: str,
) -> ThinkingStream:
    """Stream Gemini response tokens and separate thoughts."""
    client = _get_client()
    gen_config = _build_gen_config(config)
    if config.thinking_level is not None:
        gen_config["include_thoughts"] = True

    async def _generate():
        stream = await client.aio.models.generate_content_stream(
            model=config.model_id,
            contents=messages,
            config=_build_generate_config(gen_config, system_prompt),
        )
        async for chunk in stream:
            if chunk.candidates:
                for candidate in chunk.candidates:
                    if candidate.content and candidate.content.parts:
                        for part in candidate.content.parts:
                            is_thought = getattr(part, 'thought', False)
                            text = getattr(part, 'text', '')
                            if text:
                                if is_thought:
                                    wrapper._thinking_parts.append(text)
                                    yield {"type": "thinking", "text": text}
                                else:
                                    yield {"type": "text", "text": text}
            elif chunk.text:
                yield {"type": "text", "text": chunk.text}
        wrapper._finalize()

    wrapper = ThinkingStream(_generate())
    return wrapper


_THINKING_BUDGETS = {"low": 1024, "medium": 4096, "high": -1}


def _build_generate_config(gen_config: dict, system_prompt: str) -> types.GenerateContentConfig:
    """Build the full GenerateContentConfig including thinking support."""
    kwargs = {
        "system_instruction": system_prompt,
        "temperature": gen_config["temperature"],
        "top_p": gen_config.get("top_p"),
        "max_output_tokens": gen_config["max_output_tokens"],
    }
    thinking_level = gen_config.get("thinking_level")
    if thinking_level:
        budget = _THINKING_BUDGETS.get(thinking_level, 0)
        kwargs["thinking_config"] = types.ThinkingConfig(
            thinking_budget=budget,
            include_thoughts=gen_config.get("include_thoughts", False)
        )
    return types.GenerateContentConfig(**kwargs)


def _build_gen_config(config: ModelConfig) -> dict:
    """Build generation config dict from ModelConfig."""
    gc = {
        "temperature": config.temperature if config.temperature is not None else 1.0,
        "max_output_tokens": config.max_tokens,
    }
    if config.top_p is not None:
        gc["top_p"] = config.top_p
    if config.thinking_level is not None:
        gc["thinking_level"] = config.thinking_level
    return gc
