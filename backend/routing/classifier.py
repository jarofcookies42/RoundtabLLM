import json
import logging
import hashlib
from typing import Dict, Any

from ..config import REGULAR_MODELS, COMPACTION_MODEL_KEY
from ..llm.router import CLIENTS

logger = logging.getLogger("roundtable.routing.classifier")

# Simple in-memory cache for prompt classifications
_classification_cache: Dict[str, Dict[str, Any]] = {}

SYSTEM_PROMPT = """You are a task classification assistant for a multi-model roundtable.
Categorize the user's prompt into exactly one of these categories:
- coding_agentic: complex programming, software architecture, multi-file code generation, debugging, algorithms, logic.
- science_reasoning: physics, chemistry, biology, graduate-level academic analysis, scientific hypotheses.
- math: math competitions, mathematical proofs, symbolic logic, complex word problems.
- writing: essays, drafting, copywriting, structural revisions, research summaries.
- tool_use: CLI utility commands, system configurations, automation scripts, direct tool invocation requests.
- factuality_sensitive: general question answering, definitions, historical facts, citations lookup.
- creative: roleplay, storytelling, game rules design, poetry.
- ambiguous: short greetings, brief chat follow-ups, simple feedback ("ok", "yes", "thanks").

Output ONLY a raw JSON object with this schema, no markdown wrapping, no explanation outside the JSON:
{
  "category": "one_of_the_above_categories",
  "complexity": "low" | "medium" | "high",
  "explanation": "one sentence explanation"
}"""


def _get_prompt_hash(prompt: str) -> str:
    """Generate MD5 hash of prompt for caching."""
    return hashlib.md5(prompt.strip().encode("utf-8")).hexdigest()


async def classify_prompt(prompt: str) -> Dict[str, Any]:
    """
    Classify a user prompt using a fast, low-cost model.
    Caches results in memory to avoid duplicate API calls and latency.
    """
    clean_prompt = prompt.strip()
    if not clean_prompt:
        return {"category": "ambiguous", "complexity": "low", "explanation": "Empty prompt"}

    prompt_hash = _get_prompt_hash(clean_prompt)
    if prompt_hash in _classification_cache:
        logger.info("Task classification cache hit for hash %s", prompt_hash)
        return _classification_cache[prompt_hash]

    logger.info("Classifying prompt (length: %d)...", len(clean_prompt))
    
    # Resolve background runner model
    config = REGULAR_MODELS[COMPACTION_MODEL_KEY]
    client = CLIENTS[config.provider]
    
    formatted_messages = [
        {"role": "user", "model": "user", "name": "Jack", "content": f"Please classify this prompt:\n\n{clean_prompt}"}
    ]
    formatted = client.format_history(formatted_messages, COMPACTION_MODEL_KEY)

    try:
        raw_response = await client.call(formatted, config, SYSTEM_PROMPT)
        raw_response = raw_response.strip()

        # Strip markdown json code fences if model outputted them
        if raw_response.startswith("```"):
            raw_response = raw_response.split("\n", 1)[1] if "\n" in raw_response else raw_response[3:]
            if raw_response.endswith("```"):
                raw_response = raw_response[:-3].strip()
            if raw_response.startswith("json"):
                raw_response = raw_response[4:].strip()

        result = json.loads(raw_response)
        
        # Verify schema
        category = result.get("category", "ambiguous")
        complexity = result.get("complexity", "medium")
        explanation = result.get("explanation", "")
        
        classification = {
            "category": category,
            "complexity": complexity,
            "explanation": explanation
        }
        
        # Store in cache
        _classification_cache[prompt_hash] = classification
        logger.info("Prompt classified as: %s (complexity: %s)", category, complexity)
        return classification

    except Exception as e:
        logger.error("Failed to classify prompt: %s", str(e), exc_info=True)
        # Fall back gracefully to ambiguous/medium
        return {
            "category": "ambiguous",
            "complexity": "medium",
            "explanation": f"Fallback due to classification error: {str(e)}"
        }
