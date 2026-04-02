"""
AutoDream — memory consolidation via dream passes.

Scans recent conversation transcripts, extracts durable facts, compares against
existing memory topic files, and generates a proposed diff for user review.

Never runs inline with live conversations — always a separate process.
"""
import json
import logging
from datetime import datetime
from sqlmodel import Session, select

import anthropic

from ..config import ANTHROPIC_API_KEY
from ..models import DreamLog, MemoryFile, Conversation, Message

logger = logging.getLogger("roundtable.autodream")

MAX_TRANSCRIPT_CHARS = 60000  # ~15K tokens
MEMORY_CAP_CHARS = 25000
MEMORY_CAP_LINES = 200

DREAM_PROMPT = """You are a memory consolidation agent performing a "dream pass" — reviewing recent conversation transcripts to update a user's persistent memory files.

## Current memory state
Total size: {total_chars} chars, {total_lines} lines across {num_topics} topic files.

{topic_sections}

## Recent conversation transcripts
{transcripts}

## Your job

Phase 1 — GATHER: Identify NEW durable facts from the transcripts. Look for: preferences, decisions, project updates, relationship changes, completed tasks, new skills, new contacts, schedule changes. Do NOT extract: greetings, transient debugging, small talk, questions fully resolved in-conversation.

Phase 2 — CONSOLIDATE: Identify information in existing topic files that should be updated based on the transcripts. Merge related observations rather than keeping both. Examples:
- "user might prefer X" + transcript confirms X → replace old entry with confirmed fact
- "project status: planning" + transcript shows it shipped → update to shipped
- Convert vague insights into concrete facts where transcripts support it

Phase 3 — PRUNE: Identify stale, duplicated, or contradicted entries across topic files that should be removed or merged.

## Output format

Output a JSON object with this exact structure:
{{
  "additions": [
    {{"topic": "projects", "content": "text to append", "reason": "why"}},
  ],
  "updates": [
    {{"topic": "thesis", "old_content": "exact substring to replace", "new_content": "replacement text", "reason": "why"}}
  ],
  "deletions": [
    {{"topic": "projects", "content": "exact substring to remove", "reason": "why"}}
  ],
  "summary": "2-3 sentence summary of what changed and why",
  "no_changes_needed": false
}}

## Constraints

- HARD CAP: Total memory across all topic files must stay under {cap_chars} chars / {cap_lines} lines. Current: {total_chars} chars, {total_lines} lines. If adding new content would exceed this, you MUST also propose deletions or merges to stay under the cap.
- Never reduce any single topic file by more than 50% in one dream pass. If a topic needs heavy pruning, flag it in the summary and spread the work across multiple passes.
- Merge related observations rather than keeping duplicates.
- Convert vague insights into concrete facts where the transcripts support it.
- Memory is a hint system, not a source of truth. Do not consolidate speculative or uncertain information as if it were confirmed.
- Be conservative. Only propose changes you're confident about. When in doubt, leave it alone. The user will review every proposed change before it's applied.
- Use exact substrings for old_content in updates and content in deletions — the apply step does literal string matching.
- Output ONLY the JSON object. No markdown fences, no explanation outside the JSON."""


def _get_client():
    return anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)


def _format_transcripts(conversations: list[Conversation], messages_by_conv: dict[int, list[Message]]) -> str:
    """Format conversation messages as readable transcripts."""
    parts = []
    total_chars = 0

    for conv in conversations:
        msgs = messages_by_conv.get(conv.id, [])
        if not msgs:
            continue

        lines = [f"--- Conversation {conv.id} ({conv.mode} / {conv.protocol}) ---"]
        for m in msgs:
            lines.append(f"[{m.name}]: {m.content}")

        transcript = "\n".join(lines)

        if total_chars + len(transcript) > MAX_TRANSCRIPT_CHARS:
            break

        parts.append(transcript)
        total_chars += len(transcript)

    return "\n\n".join(parts)


async def generate_dream(
    session: Session,
    recent_conversation_ids: list[int] | None = None,
) -> dict:
    """
    Run a dream pass: scan recent conversations, propose memory updates.

    Returns {"dream_id": int, "proposed_changes": dict, "summary": str, "error": str|None}
    """
    # --- Acquire consolidation lock ---
    pending = session.exec(
        select(DreamLog).where(DreamLog.status == "pending")
    ).first()
    if pending:
        return {"error": "A dream is already in progress", "dream_id": pending.id}

    dream = DreamLog(status="pending")
    session.add(dream)
    session.commit()
    session.refresh(dream)

    try:
        # --- Orient: load current memory state ---
        topic_files = session.exec(
            select(MemoryFile).where(MemoryFile.file_type == "topic")
        ).all()

        if not topic_files:
            dream.status = "failed"
            dream.summary = "No memory topic files found"
            session.add(dream)
            session.commit()
            return {"error": "No memory topic files found", "dream_id": dream.id}

        total_chars = sum(len(f.content) for f in topic_files)
        total_lines = sum(f.content.count("\n") + 1 for f in topic_files)
        num_topics = len(topic_files)

        topic_sections = ""
        for f in topic_files:
            lines = f.content.count("\n") + 1
            topic_sections += f"\n### Topic: {f.key} ({lines} lines, {len(f.content)} chars)\n{f.content}\n"

        # --- Gather: load recent conversations ---
        if recent_conversation_ids:
            conversations = session.exec(
                select(Conversation)
                .where(Conversation.id.in_(recent_conversation_ids))  # type: ignore
                .order_by(Conversation.created_at)  # type: ignore
            ).all()
        else:
            # Find last successful dream cutoff
            last_dream = session.exec(
                select(DreamLog)
                .where(DreamLog.status.in_(["approved", "partially_approved"]))  # type: ignore
                .order_by(DreamLog.created_at.desc())  # type: ignore
            ).first()

            if last_dream:
                conversations = session.exec(
                    select(Conversation)
                    .where(Conversation.created_at > last_dream.created_at)  # type: ignore
                    .order_by(Conversation.created_at)  # type: ignore
                ).all()
            else:
                conversations = session.exec(
                    select(Conversation)
                    .order_by(Conversation.created_at.desc())  # type: ignore
                ).all()[:5]
                conversations = list(reversed(conversations))

        if not conversations:
            dream.status = "failed"
            dream.summary = "No new conversations since last dream"
            session.add(dream)
            session.commit()
            return {"error": "No new conversations to process", "dream_id": dream.id}

        conv_ids = [c.id for c in conversations]

        # Load all messages for these conversations
        all_messages = session.exec(
            select(Message)
            .where(Message.conversation_id.in_(conv_ids))  # type: ignore
            .order_by(Message.created_at)  # type: ignore
        ).all()

        messages_by_conv: dict[int, list[Message]] = {}
        for m in all_messages:
            messages_by_conv.setdefault(m.conversation_id, []).append(m)

        transcripts = _format_transcripts(conversations, messages_by_conv)

        if not transcripts.strip():
            dream.status = "failed"
            dream.summary = "No message content found in conversations"
            session.add(dream)
            session.commit()
            return {"error": "No message content to process", "dream_id": dream.id}

        # --- Consolidate + Prune: call Claude ---
        prompt = DREAM_PROMPT.format(
            total_chars=total_chars,
            total_lines=total_lines,
            num_topics=num_topics,
            topic_sections=topic_sections,
            transcripts=transcripts,
            cap_chars=MEMORY_CAP_CHARS,
            cap_lines=MEMORY_CAP_LINES,
        )

        client = _get_client()
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system="You are a memory consolidation agent. Output only valid JSON.",
            messages=[{"role": "user", "content": prompt}],
        )

        # Parse response
        raw_text = response.content[0].text.strip()
        # Strip markdown fences if present
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1] if "\n" in raw_text else raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3].strip()

        token_cost = (response.usage.input_tokens or 0) + (response.usage.output_tokens or 0)

        try:
            proposed = json.loads(raw_text)
        except json.JSONDecodeError as e:
            dream.status = "failed"
            dream.summary = f"Failed to parse dream response as JSON: {e}"
            dream.token_cost = token_cost
            dream.conversations_processed = json.dumps(conv_ids)
            session.add(dream)
            session.commit()
            return {"error": f"JSON parse error: {e}", "dream_id": dream.id}

        # Store results on dream log
        dream.proposed_changes = json.dumps(proposed)
        dream.conversations_processed = json.dumps(conv_ids)
        dream.summary = proposed.get("summary", "")
        dream.token_cost = token_cost
        # Keep status as "pending" — user must review
        session.add(dream)
        session.commit()

        logger.info(
            "Dream %d complete: %d additions, %d updates, %d deletions, %d tokens",
            dream.id,
            len(proposed.get("additions", [])),
            len(proposed.get("updates", [])),
            len(proposed.get("deletions", [])),
            token_cost,
        )

        return {
            "dream_id": dream.id,
            "proposed_changes": proposed,
            "summary": proposed.get("summary", ""),
            "conversations_processed": conv_ids,
            "token_cost": token_cost,
            "error": None,
        }

    except Exception as e:
        logger.error("Dream %d failed: %s", dream.id, str(e), exc_info=True)
        dream.status = "failed"
        dream.summary = f"Error: {str(e)}"
        session.add(dream)
        session.commit()
        return {"error": str(e), "dream_id": dream.id}


def apply_dream_changes(
    session: Session,
    dream_id: int,
    approved_indices: list[int],
) -> dict:
    """
    Apply user-approved changes from a dream pass to memory topic files.

    approved_indices index into the combined list: additions + updates + deletions (in that order).
    """
    dream = session.get(DreamLog, dream_id)
    if not dream:
        return {"error": "Dream not found"}
    if dream.status != "pending":
        return {"error": f"Dream is already {dream.status}"}

    proposed = json.loads(dream.proposed_changes or "{}")
    additions = proposed.get("additions", [])
    updates = proposed.get("updates", [])
    deletions = proposed.get("deletions", [])

    # Combined list for index mapping
    all_changes = (
        [{"type": "add", **a} for a in additions]
        + [{"type": "update", **u} for u in updates]
        + [{"type": "delete", **d} for d in deletions]
    )

    if not approved_indices:
        dream.status = "rejected"
        dream.applied_changes = json.dumps([])
        session.add(dream)
        session.commit()
        return {"status": "rejected", "applied": 0, "skipped": 0}

    applied = []
    skipped = []
    conv_ids = json.loads(dream.conversations_processed or "[]")
    provenance = json.dumps({"dream_id": dream_id, "conversations": conv_ids})

    def _tag_provenance(topic_file):
        """Set provenance fields on a modified topic file."""
        topic_file.source = "autodream"
        topic_file.last_modified_by = "autodream"
        topic_file.derived_from = provenance
        topic_file.updated_at = datetime.utcnow()

    for idx in approved_indices:
        if idx < 0 or idx >= len(all_changes):
            skipped.append({"index": idx, "reason": "Index out of range"})
            continue

        change = all_changes[idx]
        topic_key = change.get("topic")

        topic_file = session.exec(
            select(MemoryFile).where(MemoryFile.key == topic_key)
        ).first()

        if not topic_file:
            skipped.append({"index": idx, "reason": f"Topic '{topic_key}' not found"})
            continue

        if change["type"] == "add":
            topic_file.content = topic_file.content.rstrip() + "\n\n" + change["content"]
            _tag_provenance(topic_file)
            session.add(topic_file)
            applied.append(change)

        elif change["type"] == "update":
            old = change.get("old_content", "")
            new = change.get("new_content", "")
            if old and old in topic_file.content:
                topic_file.content = topic_file.content.replace(old, new, 1)
                topic_file.updated_at = datetime.utcnow()
                session.add(topic_file)
                applied.append(change)
            else:
                skipped.append({"index": idx, "reason": "Substring not found in topic file"})

        elif change["type"] == "delete":
            content = change.get("content", "")
            if content and content in topic_file.content:
                topic_file.content = topic_file.content.replace(content, "", 1)
                # Clean up double newlines left by deletion
                while "\n\n\n" in topic_file.content:
                    topic_file.content = topic_file.content.replace("\n\n\n", "\n\n")
                topic_file.updated_at = datetime.utcnow()
                session.add(topic_file)
                applied.append(change)
            else:
                skipped.append({"index": idx, "reason": "Substring not found in topic file"})

    # Update dream log
    if len(applied) == len(approved_indices):
        dream.status = "approved"
    elif len(applied) > 0:
        dream.status = "partially_approved"
    else:
        dream.status = "rejected"

    dream.applied_changes = json.dumps(applied)
    session.add(dream)
    session.commit()

    # Calculate current memory stats
    all_topics = session.exec(
        select(MemoryFile).where(MemoryFile.file_type == "topic")
    ).all()
    total_chars = sum(len(f.content) for f in all_topics)
    total_lines = sum(f.content.count("\n") + 1 for f in all_topics)

    warning = None
    if total_chars > MEMORY_CAP_CHARS or total_lines > MEMORY_CAP_LINES:
        warning = f"Memory exceeds cap: {total_chars} chars / {total_lines} lines (cap: {MEMORY_CAP_CHARS} / {MEMORY_CAP_LINES})"

    return {
        "status": dream.status,
        "applied": len(applied),
        "skipped": len(skipped),
        "skipped_details": skipped,
        "memory_stats": {"chars": total_chars, "lines": total_lines},
        "warning": warning,
    }
