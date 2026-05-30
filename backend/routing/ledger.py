import json
import logging
from typing import Dict, Any, List
from datetime import datetime
from sqlmodel import Session, select

from ..config import REGULAR_MODELS, COMPACTION_MODEL_KEY
from ..llm.router import CLIENTS
from ..models import ModelOutcome, ModelScoreInternal

logger = logging.getLogger("roundtable.routing.ledger")

EVAL_SYSTEM_PROMPT = """You are an objective academic evaluator measuring model contributions in a roundtable deliberation.
Analyze how much of each proposer's ideas, arguments, facts, or recommendations were incorporated or reflected in the final synthesis.

Assign a score from 0.0 to 1.0 for each model:
- 1.0: Entirely adopted, core of the synthesis.
- 0.8: Strongly incorporated, multiple main points adopted.
- 0.5: Moderately incorporated, some elements present.
- 0.2: Slightly incorporated, minor mention or mostly rejected/superseded.
- 0.0: Not present at all, ignored or fully contradicted.

Output ONLY a JSON object mapping model keys to their numerical scores, no markdown code fences, no extra text:
{
  "model_key_1": 0.8,
  "model_key_2": 0.2
}"""


async def evaluate_and_log_outcomes(
    session: Session,
    conversation_id: int,
    category: str,
    user_message: str,
    proposals: Dict[str, str],        # model_key -> response_content
    synthesis_content: str
) -> Dict[str, float]:
    """
    Run an LLM-based evaluation of each participating model's contribution
    to the final synthesis. Logs outcomes to DB and updates internal ledgers.
    """
    if not proposals or not synthesis_content:
        return {}

    logger.info("Evaluating round outcomes for conversation %d...", conversation_id)
    
    # Format proposals for the evaluator prompt
    proposals_text = []
    for model_key, content in proposals.items():
        disp_name = REGULAR_MODELS.get(model_key, {}).display_name if model_key in REGULAR_MODELS else model_key
        proposals_text.append(f"Model: {model_key} (Display Name: {disp_name})\nResponse:\n{content}\n")
    
    eval_prompt = (
        f"User Message: {user_message}\n\n"
        f"Final Synthesis:\n{synthesis_content}\n\n"
        f"--- Proposer Responses ---\n\n"
        + "\n---\n\n".join(proposals_text)
    )

    # Call fast background model
    config = REGULAR_MODELS[COMPACTION_MODEL_KEY]
    client = CLIENTS[config.provider]
    
    formatted_messages = [
        {"role": "user", "model": "user", "name": "Jack", "content": eval_prompt}
    ]
    formatted = client.format_history(formatted_messages, COMPACTION_MODEL_KEY)

    scores: Dict[str, float] = {}
    try:
        raw_eval = await client.call(formatted, config, EVAL_SYSTEM_PROMPT)
        raw_eval = raw_eval.strip()

        # Strip fences
        if raw_eval.startswith("```"):
            raw_eval = raw_eval.split("\n", 1)[1] if "\n" in raw_eval else raw_eval[3:]
            if raw_eval.endswith("```"):
                raw_eval = raw_eval[:-3].strip()
            if raw_eval.startswith("json"):
                raw_eval = raw_eval[4:].strip()

        scores_raw = json.loads(raw_eval)
        for k, val in scores_raw.items():
            if k in proposals:
                scores[k] = float(val)

        logger.info("Evaluator returned scores: %s", scores)

    except Exception as e:
        logger.error("Failed to run post-round outcome evaluation: %s", str(e), exc_info=True)
        # Default to neutral 0.5 for participants on failure
        scores = {k: 0.5 for k in proposals.keys()}

    # Log outcomes and update rolling scores in DB
    try:
        for model_key, score in scores.items():
            # 1. Save individual model outcome
            outcome = ModelOutcome(
                conversation_id=conversation_id,
                model=model_key,
                position_in_synthesis=score,
                dissent_count=0,          # Stub: can update in router if needed
                user_accepted=None,       # Surface later if thumbs-up/down is added
                category=category,
                created_at=datetime.utcnow()
            )
            session.add(outcome)
            
            # 2. Update rolling average Bayesian score
            stmt = select(ModelScoreInternal).where(
                ModelScoreInternal.model == model_key,
                ModelScoreInternal.category == category
            )
            score_record = session.exec(stmt).first()
            if not score_record:
                score_record = ModelScoreInternal(
                    model=model_key,
                    category=category,
                    rolling_average=score,
                    sample_count=1,
                    updated_at=datetime.utcnow()
                )
            else:
                n = score_record.sample_count
                score_record.rolling_average = ((score_record.rolling_average * n) + score) / (n + 1)
                score_record.sample_count = n + 1
                score_record.updated_at = datetime.utcnow()
            session.add(score_record)
            
        session.commit()
        logger.info("Successfully updated internal performance ledger.")

    except Exception as e:
        logger.error("Failed to update database with outcomes: %s", str(e), exc_info=True)

    return scores
