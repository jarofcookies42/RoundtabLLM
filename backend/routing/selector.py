import os
import json
import logging
from typing import List, Dict, Tuple, Any
from sqlmodel import Session, select

from ..config import ModelConfig, ANCHOR_ORDERS, REGULAR_MODELS, OVERDRIVE_MODELS
from ..models import ModelScoreInternal

logger = logging.getLogger("roundtable.routing.selector")

# Path to benchmark priors file
BENCHMARK_PRIORS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "benchmark_priors.json"
)

# Benchmark category mapping to json key
CATEGORY_MAP = {
    "coding_agentic": "coding_agentic",
    "coding_snippet": "coding_agentic",
    "science_reasoning": "science_reasoning",
    "math": "math",
    "writing": "writing",
    "tool_use": "tool_use",
    "factuality_sensitive": "science_reasoning",
    "creative": "writing",
    "ambiguous": "writing"
}


def load_external_priors() -> List[Dict[str, Any]]:
    """Load benchmark priors from static JSON file."""
    try:
        if os.path.exists(BENCHMARK_PRIORS_PATH):
            with open(BENCHMARK_PRIORS_PATH, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.error("Error loading benchmark priors: %s", str(e), exc_info=True)
    return []


def select_models(
    session: Session,
    category: str,
    mode: str,
    anchor_mode: str,
    enabled_models: List[str]
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Ranks and selects models for a round by combining external benchmark priors 
    with internal rolling averages.
    
    Returns (selected_keys, rationale_logs)
    """
    # 1. Resolve configuration model dictionary and keys
    models_pool = REGULAR_MODELS if mode == "regular" else OVERDRIVE_MODELS
    pool_keys = [k for k in models_pool.keys() if k in enabled_models]
    
    if len(pool_keys) <= 3 and mode == "regular":
        # Don't route if we have 3 or fewer models enabled anyway
        return pool_keys, [{"model": k, "score": 1.0, "notes": "Forced (small pool)"} for k in pool_keys]

    # Resolve target benchmark category
    benchmark_cat = CATEGORY_MAP.get(category, "writing")
    
    # Load external priors
    priors_list = load_external_priors()
    priors_by_model = {p["model_key"]: p["categories"].get(benchmark_cat, {}).get("score", 0.5) for p in priors_list}

    # Query internal scores
    internal_scores = session.exec(
        select(ModelScoreInternal).where(ModelScoreInternal.category == category)
    ).all()
    internal_map = {item.model: (item.rolling_average, item.sample_count) for item in internal_scores}

    # Score each model in the enabled pool
    model_scores: List[Tuple[str, float, str]] = []
    for model_key in pool_keys:
        prior_score = priors_by_model.get(model_key, 0.5)
        rolling_avg, sample_count = internal_map.get(model_key, (0.5, 0))
        
        # Bayesian weight shift: decays prior weight as sample size grows (target N=50)
        weight_internal = min(0.4, (sample_count / 50.0) * 0.4)
        weight_external = 1.0 - weight_internal
        
        score = (weight_external * prior_score) + (weight_internal * rolling_avg)
        note = f"Combined (prior: {prior_score:.2f} * {weight_external:.2f} + internal: {rolling_avg:.2f} * {weight_internal:.2f}, N={sample_count})"
        model_scores.append((model_key, score, note))

    # Sort models by score descending
    model_scores.sort(key=lambda x: x[1], reverse=True)

    # 2. Determine target selection size
    target_count = 3 if mode == "regular" else 5
    selected_scores = model_scores[:target_count]
    selected_keys = [item[0] for item in selected_scores]

    # 3. Anchor preservation: Ensure anchor goes last
    order = ANCHOR_ORDERS[anchor_mode]
    active_order = [k for k in order if k in pool_keys]
    if not active_order:
        # Fallback to absolute pool keys
        return pool_keys, [{"model": k, "score": 0.0, "notes": "No order matched"} for k in pool_keys]

    anchor_key = active_order[-1]
    
    if anchor_key not in selected_keys:
        logger.info("Forcing inclusion of anchor model: %s", anchor_key)
        # Find anchor in the scores list
        anchor_item = next((item for item in model_scores if item[0] == anchor_key), None)
        if anchor_item:
            # Replace the lowest-scoring selected model with the anchor
            replaced_key = selected_keys[-1]
            selected_scores[-1] = (anchor_item[0], anchor_item[1], anchor_item[2] + f" (Forced anchor replacement of {replaced_key})")
            selected_keys[-1] = anchor_key

    # Sort selected keys according to anchor order
    final_keys = [k for k in active_order if k in selected_keys]
    
    # Construct rationale logs
    rationale = []
    for key, score, note in model_scores:
        chosen = key in final_keys
        rationale.append({
            "model": models_pool[key].display_name,
            "key": key,
            "score": round(score, 3),
            "chosen": chosen,
            "note": note
        })

    logger.info("Selected models for roundtable: %s", final_keys)
    return final_keys, rationale
