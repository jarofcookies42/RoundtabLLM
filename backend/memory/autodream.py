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

from ..config import REGULAR_MODELS, AUTODREAM_MODEL_KEY
from ..prompts import DREAM_PROMPT, DREAM_SYSTEM_PROMPT
from ..models import DreamLog, MemoryFile, Conversation, Message

logger = logging.getLogger("roundtable.autodream")

MAX_TRANSCRIPT_CHARS = 60000  # ~15K tokens
MEMORY_CAP_CHARS = 25000
MEMORY_CAP_LINES = 200


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
    # Clear stale pending dreams (older than 30 minutes)
    from datetime import datetime, timedelta
    stale_cutoff = datetime.utcnow() - timedelta(minutes=30)
    stale_dreams = session.exec(
        select(DreamLog)
        .where(DreamLog.status == "pending")
        .where(DreamLog.created_at < stale_cutoff)
    ).all()
    for sd in stale_dreams:
        sd.status = "failed"
        sd.summary = "Consolidation pass timed out (stale check)"
        session.add(sd)
    if stale_dreams:
        session.commit()

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

        # Load all messages for these conversations (excluding errors)
        all_messages = session.exec(
            select(Message)
            .where(Message.conversation_id.in_(conv_ids))  # type: ignore
            .where(Message.is_error == False)  # noqa: E712
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

        # --- Consolidate + Prune: call Dynamic Client ---
        prompt = DREAM_PROMPT.format(
            total_chars=total_chars,
            total_lines=total_lines,
            num_topics=num_topics,
            topic_sections=topic_sections,
            transcripts=transcripts,
            cap_chars=MEMORY_CAP_CHARS,
            cap_lines=MEMORY_CAP_LINES,
        )

        # Resolve dynamic client to avoid circular imports
        from ..llm.router import CLIENTS
        config = REGULAR_MODELS[AUTODREAM_MODEL_KEY]
        client = CLIENTS[config.provider]
        system_prompt = DREAM_SYSTEM_PROMPT

        temp_messages = [{"role": "user", "model": "user", "name": "Jack", "content": prompt}]
        formatted = client.format_history(temp_messages, AUTODREAM_MODEL_KEY)

        raw_text = await client.call(formatted, config, system_prompt)
        raw_text = raw_text.strip()

        # Strip markdown fences if present
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1] if "\n" in raw_text else raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3].strip()

        # Estimate token cost
        token_cost = (len(prompt) + len(raw_text)) // 4

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

    # Simulate and check memory cap before applying
    all_topics = session.exec(
        select(MemoryFile).where(MemoryFile.file_type == "topic")
    ).all()
    simulated_content = {f.key: f.content for f in all_topics}

    for idx in approved_indices:
        if idx < 0 or idx >= len(all_changes):
            continue
        change = all_changes[idx]
        topic_key = change.get("topic")
        if topic_key not in simulated_content:
            continue
        current = simulated_content[topic_key]
        if change["type"] == "add":
            simulated_content[topic_key] = current.rstrip() + "\n\n" + change["content"]
        elif change["type"] == "update":
            old = change.get("old_content", "")
            new = change.get("new_content", "")
            if old and old in current:
                simulated_content[topic_key] = current.replace(old, new, 1)
        elif change["type"] == "delete":
            content = change.get("content", "")
            if content and content in current:
                current_replaced = current.replace(content, "", 1)
                while "\n\n\n" in current_replaced:
                    current_replaced = current_replaced.replace("\n\n\n", "\n\n")
                simulated_content[topic_key] = current_replaced

    total_chars = sum(len(content) for content in simulated_content.values())
    total_lines = sum(content.count("\n") + 1 for content in simulated_content.values())

    if total_chars > MEMORY_CAP_CHARS or total_lines > MEMORY_CAP_LINES:
        dream.status = "failed"
        dream.summary = f"Aborted: applying approved changes would exceed memory cap: {total_chars} chars / {total_lines} lines (cap: {MEMORY_CAP_CHARS} / {MEMORY_CAP_LINES})"
        session.add(dream)
        session.commit()
        return {
            "error": f"Applying these changes would exceed memory cap: {total_chars} chars / {total_lines} lines (cap: {MEMORY_CAP_CHARS} / {MEMORY_CAP_LINES})",
            "dream_id": dream_id
        }

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
