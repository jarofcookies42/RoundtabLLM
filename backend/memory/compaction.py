"""
Compaction pipeline — summarizes older conversation messages to reduce context size.

Keeps recent messages verbatim and replaces older ones with a Claude-generated
summary. Compacted messages stay in the DB for export/audit but are excluded
from the history sent to models.
"""
import logging
from sqlmodel import Session, select

import anthropic

from ..config import ANTHROPIC_API_KEY
from ..models import Message

logger = logging.getLogger("roundtable.compaction")

COMPACTION_THRESHOLD = 30000  # tokens (~120K chars / 4)
MIN_MESSAGES_TO_COMPACT = 10  # need at least this many before compacting

COMPACTION_PROMPT = """You are compacting a multi-AI roundtable conversation to save context space. Below is the older portion of the conversation that needs to be summarized.

Participants: Jack (human user), Claude, GPT-5.4, Gemini 3.1 Pro, Grok 4.20

Transcript to summarize:
{transcript}

Create a concise summary that preserves:
- Key decisions and conclusions reached
- Important disagreements between models (who said what)
- Action items or commitments Jack made
- Any facts, data, or references that were shared
- The overall arc of the discussion

Do NOT preserve:
- Greetings, pleasantries, meta-commentary about the roundtable itself
- Redundant agreement ("I agree with Claude" when the agreement adds nothing)
- Test messages or debugging

Format as a compact narrative paragraph, not bullet points. Keep it under 500 tokens. Start with "Earlier in this conversation:" so models know this is a summary, not a real message."""


def _get_client():
    return anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)


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

    # Call Claude for summary
    client = _get_client()
    prompt = COMPACTION_PROMPT.format(transcript=transcript)

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system="You are a conversation compactor. Output only the summary.",
            messages=[{"role": "user", "content": prompt}],
        )
        summary = response.content[0].text.strip()
        summary_tokens = (response.usage.input_tokens or 0) + (response.usage.output_tokens or 0)
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
