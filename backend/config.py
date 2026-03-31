"""
Configuration for LLM Roundtable.
All model configs, mode definitions, and env var loading.
"""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv(override=True)

# --- API Keys ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GOOGLE_AI_API_KEY = os.getenv("GOOGLE_AI_API_KEY", "")
GROK_API_KEY = os.getenv("GROK_API_KEY", "")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "changeme")

# --- Database ---
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./roundtable.db")

# --- Model Definitions ---

# TODO: Per-model thinking/reasoning level sliders — let the user override thinking_level,
#       reasoning_effort, and thinking.budget_tokens per model from the UI. Would need a
#       new API param on ChatRequest and a slider component next to each model chip.

@dataclass
class ModelConfig:
    """Config for a single model in a given mode."""
    model_id: str          # API model string
    provider: str          # "anthropic", "openai", "gemini", "grok"
    display_name: str
    color: str             # hex color for UI
    icon: str              # unicode icon
    temperature: float | None = None       # None = don't pass (Claude w/ thinking, GPT-5.4)
    max_tokens: int = 1024
    # Claude-specific
    thinking: dict | None = None           # {"type": "enabled", "budget_tokens": N} or {"type": "adaptive"}
    effort: str | None = None              # "low", "medium", "high", "max"
    # OpenAI-specific
    reasoning_effort: str | None = None    # "none", "low", "medium", "high", "xhigh"
    verbosity: str | None = None           # "low", "medium", "high"
    # Gemini-specific
    thinking_level: str | None = None      # "low", "medium", "high"
    top_p: float | None = None


# ============================================================
# MODE CONFIGS
# ============================================================

REGULAR_MODELS = {
    "claude": ModelConfig(
        model_id="claude-sonnet-4-6",
        provider="anthropic",
        display_name="Claude Sonnet 4.6",
        color="#D97706",
        icon="◈",
        # temperature NOT passed when thinking is enabled
        max_tokens=8192,
        thinking={"type": "enabled", "budget_tokens": 4096},
    ),
    "gpt": ModelConfig(
        model_id="gpt-5.4",
        provider="openai",
        display_name="GPT-5.4",
        color="#10B981",
        icon="◉",
        # temperature=1 is the ONLY valid value, but for GPT-5 reasoning models
        # it's safest to just not pass it at all
        max_tokens=1024,
        reasoning_effort="none",
        verbosity="medium",
    ),
    "gemini": ModelConfig(
        model_id="gemini-3.1-pro-preview",
        provider="gemini",
        display_name="Gemini 3.1 Pro",
        color="#6366F1",
        icon="◆",
        temperature=1.0,  # MUST be 1.0, do not change
        max_tokens=2048,
        thinking_level="low",
        top_p=0.95,
    ),
    "grok": ModelConfig(
        model_id="grok-4-1-fast-non-reasoning",
        provider="grok",
        display_name="Grok",
        color="#EC4899",
        icon="✕",
        temperature=0.7,
        max_tokens=1024,
    ),
}

OVERDRIVE_MODELS = {
    "claude": ModelConfig(
        model_id="claude-opus-4-6",
        provider="anthropic",
        display_name="Claude Opus 4.6",
        color="#D97706",
        icon="◈",
        max_tokens=32000,
        thinking={"type": "adaptive"},
        effort="max",
    ),
    "gpt": ModelConfig(
        model_id="gpt-5.4",
        provider="openai",
        display_name="GPT-5.4",
        color="#10B981",
        icon="◉",
        max_tokens=2048,
        reasoning_effort="high",
        verbosity="high",
    ),
    "gemini": ModelConfig(
        model_id="gemini-3.1-pro-preview",
        provider="gemini",
        display_name="Gemini 3.1 Pro",
        color="#6366F1",
        icon="◆",
        temperature=1.0,
        max_tokens=4096,
        thinking_level="high",  # Activates Deep Think Mini
        top_p=0.95,
    ),
    "grok": ModelConfig(
        model_id="grok-4-1-fast-reasoning",
        provider="grok",
        display_name="Grok",
        color="#EC4899",
        icon="✕",
        temperature=0.9,
        max_tokens=2048,
    ),
}

# ============================================================
# ANCHOR ORDER PRESETS
# ============================================================
# The anchor (last responder) sees all other responses first.
# Order = list of model keys, last one is anchor.

ANCHOR_ORDERS = {
    # Knowledge anchor: Claude last (best at professional knowledge work)
    "knowledge": ["grok", "gpt", "gemini", "claude"],
    # Abstract anchor: Gemini last (best at abstract reasoning, novel logic)
    "abstract": ["grok", "gpt", "claude", "gemini"],
}


def get_active_config(mode: str, anchor: str, enabled_models: list[str] | None = None):
    """
    Returns (models_dict, ordered_keys) for the current mode and anchor setting.

    mode: "regular" or "overdrive"
    anchor: "knowledge" or "abstract"
    enabled_models: optional list of model keys to include (default: all)
    """
    models = REGULAR_MODELS if mode == "regular" else OVERDRIVE_MODELS
    order = ANCHOR_ORDERS[anchor]

    if enabled_models:
        order = [k for k in order if k in enabled_models and k in models]

    return models, order
