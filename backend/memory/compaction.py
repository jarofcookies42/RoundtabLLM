"""
Compaction pipeline — summarizes older conversation messages to reduce context size.

Keeps recent messages verbatim and replaces older ones with a model-generated
summary. Compacted messages stay in the DB for export/audit but are excluded
from the history sent to models.
"""
import logging
from sqlmodel import Session, select

from ..config import REGULAR_MODELS, COMPACTION_MODEL_KEY
from ..prompts import COMPACTION_PROMPT, COMPACTION_SYSTEM_PROMPT
from ..models import Message

logger = logging.getLogger("roundtable.compaction")

COMPACTION_THRESHOLD = 30000  # tokens (~120K chars / 4)
MIN_MESSAGES_TO_COMPACT = 10  # need at least this many before compacting


def estimate_tokens(messages: list) -> int:
    """Rough token estimate: chars / 4."""
    total = 0
    for m in messages:
        content = m.content if hasattr(m, "content") else m.get("content", "")
        total += len(content)
    return total // 4


async def compact_conversation(
    session: Session,
    conversation_id: int,
    keep_recent: int = 6,
) -> dict:
    """
    Summarize older messages in a conversation to reduce context size.

    Returns stats dict or {"skipped": True, "reason": "..."} if not needed.
    """
    # Load all non-compacted messages
    all_messages = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .where(Message.compacted == False)  # noqa: E712
        .where(Message.model != "compaction")  # don't re-compact summaries
        .order_by(Message.created_at)  # type: ignore
    ).all()

    total = len(all_messages)
    if total < MIN_MESSAGES_TO_COMPACT:
        return {"skipped": True, "reason": f"Only {total} messages, need {MIN_MESSAGES_TO_COMPACT}+"}

    if total <= keep_recent + 4:
        return {"skipped": True, "reason": f"Only {total} messages, not enough beyond keep_recent={keep_recent}"}

    # Split into old and recent
    cutoff = total - keep_recent
    old_messages = all_messages[:cutoff]
    recent_messages = all_messages[cutoff:]

    original_tokens = estimate_tokens(old_messages)

    # Format old messages as transcript
    transcript_lines = []
    for m in old_messages:
        tier_tag = f" ({m.trust_tier})" if m.trust_tier not in ("direct", "model") else ""
        transcript_lines.append(f"[{m.name}]{tier_tag}: {m.content}")
    transcript = "\n\n".join(transcript_lines)

    # Resolve client dynamically to avoid circular imports
    from ..llm.router import CLIENTS
    config = REGULAR_MODELS[COMPACTION_MODEL_KEY]
    client = CLIENTS[config.provider]

    prompt = COMPACTION_PROMPT.format(transcript=transcript)
    system_prompt = COMPACTION_SYSTEM_PROMPT

    try:
        temp_messages = [{"role": "user", "model": "user", "name": "Jack", "content": prompt}]
        formatted = client.format_history(temp_messages, COMPACTION_MODEL_KEY)
        
        summary = await client.call(formatted, config, system_prompt)
        summary = summary.strip()
        
        # Estimate summary tokens
        summary_tokens = estimate_tokens([{"content": summary}])
    except Exception as e:
        logger.error("Compaction failed for conversation %d: %s", conversation_id, str(e))
        return {"error": str(e)}

    # Create compaction summary message
    summary_msg = Message(
        conversation_id=conversation_id,
        role="system",
        model="compaction",
        name="Conversation Summary",
        content=summary,
        source="system",
        trust_tier="derived",
        protocol_role="compaction",
    )
    session.add(summary_msg)

    # Mark old messages as compacted
    for m in old_messages:
        m.compacted = True
        session.add(m)

    session.commit()

    stats = {
        "messages_compacted": len(old_messages),
        "messages_kept": len(recent_messages),
        "summary_tokens": summary_tokens,
        "original_tokens_estimate": original_tokens,
    }
    logger.info("Compacted conversation %d: %s", conversation_id, stats)
    return stats


def should_compact(messages: list, threshold: int = COMPACTION_THRESHOLD) -> bool:
    """Check if a conversation needs compaction based on token estimate."""
    return estimate_tokens(messages) > threshold
