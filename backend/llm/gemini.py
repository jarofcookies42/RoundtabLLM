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


async def call(messages: list[dict], config: ModelConfig, system_prompt: str) -> str:
    """Call Gemini and return the full text response."""
    client = _get_client()
    gen_config = _build_gen_config(config)

    response = await client.aio.models.generate_content(
        model=config.model_id,
        contents=messages,
        config=_build_generate_config(gen_config, system_prompt),
    )
    return response.text or ""


async def call_stream(
    messages: list[dict],
    config: ModelConfig,
    system_prompt: str,
) -> AsyncGenerator[str, None]:
    """Stream Gemini response tokens."""
    client = _get_client()
    gen_config = _build_gen_config(config)

    stream = await client.aio.models.generate_content_stream(
        model=config.model_id,
        contents=messages,
        config=_build_generate_config(gen_config, system_prompt),
    )
    async for chunk in stream:
        # Extract text from all candidates/parts to avoid dropping content
        if chunk.candidates:
            for candidate in chunk.candidates:
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if hasattr(part, "text") and part.text:
                            yield part.text
        elif chunk.text:
            yield chunk.text


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
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=budget)
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
