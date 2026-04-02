"""
Round-robin orchestrator + protocol routing.

Three protocols control how models interact during a round:

1. ROUNDTABLE (default): Sequential round-robin. Each model sees all previous
   responses. The anchor goes last and sees everything.

2. BLIND → SYNTHESIS: All models answer independently in parallel (no visibility).
   After all finish, the anchor gets all responses and synthesizes.

3. DEBATE: Two proposers answer in parallel (blind). A critic evaluates both
   proposals (anonymized). The arbiter synthesizes with full attribution.

All three yield the same SSE event format so the frontend doesn't need
protocol-specific rendering logic.
"""
import json
import asyncio
import logging
from typing import AsyncGenerator
from sqlmodel import Session, select

from ..config import get_active_config, ModelConfig
from ..models import Message, Conversation
from ..context import build_system_prompt, get_relevant_context, PROTOCOL_PROMPTS
from ..memory.compaction import compact_conversation, should_compact, estimate_tokens
from . import claude, openai_client, gemini, grok

logger = logging.getLogger("roundtable.router")

# Map provider names to client modules
CLIENTS = {
    "anthropic": claude,
    "openai": openai_client,
    "gemini": gemini,
    "grok": grok,
}


def _resolve_context(
    user_message: str,
    history: list[dict],
    context_mode: str,
    selected_topics: list[str] | None,
    session: Session,
) -> tuple[str, list[str]]:
    """Resolve context for a round using the memory-as-hint system."""
    recent_user_msgs = [
        m["content"] for m in history if m["role"] == "user"
    ][-3:]
    return get_relevant_context(
        user_message, recent_user_msgs, context_mode, selected_topics, session,
    )


# ============================================================
# ROUNDTABLE PROTOCOL
# ============================================================

async def run_round(
    conversation_id: int,
    user_message: str,
    mode: str,
    anchor: str,
    enabled_models: list[str],
    context_content: str,
    session: Session,
    context_mode: str = "full",
    selected_topics: list[str] | None = None,
) -> AsyncGenerator[str, None]:
    """
    Execute a full round-robin and yield SSE events.
    """
    models, order = get_active_config(mode, anchor, enabled_models)

    # Auto-compact if context pressure is high
    compact_stats = await _auto_compact_if_needed(conversation_id, session)
    if compact_stats and not compact_stats.get("skipped") and not compact_stats.get("error"):
        yield _sse({"type": "compaction", **compact_stats})

    # Accumulate messages for this round (user + each model's response)
    round_messages = _load_conversation_history(conversation_id, session)
    round_messages.append({
        "role": "user", "model": "user", "name": "Jack", "content": user_message,
    })

    # Resolve context via memory-as-hint system
    resolved_context, loaded_topics = _resolve_context(
        user_message, round_messages, context_mode, selected_topics, session,
    )
    effective_context = resolved_context if resolved_context is not None else context_content

    yield _sse({"type": "context_loaded", "topics": loaded_topics})

    for model_key in order:
        config = models[model_key]
        client = CLIENTS[config.provider]
        system_prompt = build_system_prompt(effective_context, mode, config.display_name)

        yield _sse({"type": "model_start", "model": model_key, "name": config.display_name})

        try:
            formatted = client.format_history(round_messages, model_key)
            full_response = ""
            stream = client.call_stream(formatted, config, system_prompt)
            async for delta in stream:
                full_response += delta
                yield _sse({"type": "token", "model": model_key, "delta": delta})

            thinking_content = getattr(stream, "thinking_content", None)

            _save_msg(session, conversation_id, model_key, config.display_name,
                      full_response, thinking_content=thinking_content)

            round_messages.append({
                "role": "assistant", "model": model_key,
                "name": config.display_name, "content": full_response,
            })

            yield _sse({"type": "model_done", "model": model_key, "content": full_response})

        except Exception as e:
            error_msg = str(e)
            logger.error("Model %s failed: %s", model_key, error_msg, exc_info=True)
            yield _sse({"type": "model_error", "model": model_key, "error": error_msg})

            _save_msg(session, conversation_id, model_key, config.display_name,
                      f"⚠ Error: {error_msg}", is_error=True)

    ctx_tokens = estimate_tokens(round_messages)
    yield _sse({"type": "round_done", "context_tokens": ctx_tokens, "context_limit": 30000})


# ============================================================
# BLIND → SYNTHESIS PROTOCOL
# ============================================================

async def run_blind(
    conversation_id: int,
    user_message: str,
    mode: str,
    anchor: str,
    enabled_models: list[str],
    context_content: str,
    session: Session,
    context_mode: str = "full",
    selected_topics: list[str] | None = None,
) -> AsyncGenerator[str, None]:
    """All models answer independently in parallel (blind), then the anchor synthesizes."""
    models, order = get_active_config(mode, anchor, enabled_models)

    if len(order) < 2:
        async for event in run_round(
            conversation_id, user_message, mode, anchor,
            enabled_models, context_content, session,
            context_mode=context_mode, selected_topics=selected_topics,
        ):
            yield event
        return

    # Auto-compact if needed
    compact_stats = await _auto_compact_if_needed(conversation_id, session)
    if compact_stats and not compact_stats.get("skipped") and not compact_stats.get("error"):
        yield _sse({"type": "compaction", **compact_stats})

    history = _load_conversation_history(conversation_id, session)
    history.append({"role": "user", "model": "user", "name": "Jack", "content": user_message})

    resolved_context, loaded_topics = _resolve_context(
        user_message, history, context_mode, selected_topics, session,
    )
    effective_context = resolved_context if resolved_context is not None else context_content
    yield _sse({"type": "context_loaded", "topics": loaded_topics})

    independent_keys = order[:-1]
    anchor_key = order[-1]

    event_queue: asyncio.Queue[str | None] = asyncio.Queue()
    results: dict[str, dict] = {}

    async def _stream_model(model_key: str):
        config = models[model_key]
        client = CLIENTS[config.provider]
        system_prompt = build_system_prompt(
            effective_context, mode, config.display_name, protocol="blind",
        )

        await event_queue.put(_sse({
            "type": "model_start", "model": model_key, "name": config.display_name,
            "protocol_role": "proposal",
        }))

        try:
            formatted = client.format_history(history, model_key)
            full_response = ""
            stream = client.call_stream(formatted, config, system_prompt)
            async for delta in stream:
                full_response += delta
                await event_queue.put(_sse({"type": "token", "model": model_key, "delta": delta}))

            thinking_content = getattr(stream, "thinking_content", None)
            results[model_key] = {"content": full_response, "thinking": thinking_content, "error": False}

            _save_msg(session, conversation_id, model_key, config.display_name,
                      full_response, thinking_content=thinking_content, protocol_role="proposal")

            await event_queue.put(_sse({
                "type": "model_done", "model": model_key, "content": full_response,
                "protocol_role": "proposal",
            }))

        except Exception as e:
            error_msg = str(e)
            results[model_key] = {"content": f"⚠ Error: {error_msg}", "thinking": None, "error": True}
            await event_queue.put(_sse({"type": "model_error", "model": model_key, "error": error_msg}))
            _save_msg(session, conversation_id, model_key, config.display_name,
                      f"⚠ Error: {error_msg}", is_error=True, protocol_role="proposal")

    tasks = [asyncio.create_task(_stream_model(k)) for k in independent_keys]

    async def _monitor():
        await asyncio.gather(*tasks)
        await event_queue.put(None)

    monitor = asyncio.create_task(_monitor())

    while True:
        event = await event_queue.get()
        if event is None:
            break
        yield event

    await monitor

    # Anchor synthesis
    anchor_config = models[anchor_key]
    anchor_client = CLIENTS[anchor_config.provider]

    response_summaries = []
    for i, mk in enumerate(independent_keys):
        r = results.get(mk, {})
        if not r.get("error"):
            response_summaries.append(f"**{models[mk].display_name}:**\n{r.get('content', '')}")

    synthesis_input = (
        f"Original prompt from Jack: {user_message}\n\n"
        + "\n\n---\n\n".join(response_summaries)
    )

    synthesis_system = build_system_prompt(
        effective_context, mode, anchor_config.display_name,
        protocol="blind", protocol_role_prompt=PROTOCOL_PROMPTS["synthesis"],
    )

    yield _sse({
        "type": "model_start", "model": anchor_key, "name": anchor_config.display_name,
        "protocol_role": "synthesis",
    })

    try:
        synth_history = history + [{
            "role": "user", "model": "user", "name": "Jack", "content": synthesis_input,
        }]
        formatted = anchor_client.format_history(synth_history, anchor_key)

        full_response = ""
        stream = anchor_client.call_stream(formatted, anchor_config, synthesis_system)
        async for delta in stream:
            full_response += delta
            yield _sse({"type": "token", "model": anchor_key, "delta": delta})

        thinking_content = getattr(stream, "thinking_content", None)

        _save_msg(session, conversation_id, anchor_key, anchor_config.display_name,
                  full_response, thinking_content=thinking_content,
                  protocol_role="synthesis", trust_tier="derived")

        yield _sse({
            "type": "model_done", "model": anchor_key, "content": full_response,
            "protocol_role": "synthesis",
        })

    except Exception as e:
        error_msg = str(e)
        yield _sse({"type": "model_error", "model": anchor_key, "error": error_msg})
        _save_msg(session, conversation_id, anchor_key, anchor_config.display_name,
                  f"⚠ Error: {error_msg}", is_error=True, protocol_role="synthesis")

    ctx_tokens = estimate_tokens(history)
    yield _sse({"type": "round_done", "context_tokens": ctx_tokens, "context_limit": 30000})


# ============================================================
# DEBATE PROTOCOL
# ============================================================

async def run_debate(
    conversation_id: int,
    user_message: str,
    mode: str,
    anchor: str,
    enabled_models: list[str],
    context_content: str,
    session: Session,
    debate_roles: dict[str, str] | None = None,
    context_mode: str = "full",
    selected_topics: list[str] | None = None,
) -> AsyncGenerator[str, None]:
    """
    Debate protocol: proposers → critic (anonymized) → arbiter (full attribution).
    """
    models, order = get_active_config(mode, anchor, enabled_models)

    if len(order) < 3:
        fallback = run_blind if len(order) >= 2 else run_round
        async for event in fallback(
            conversation_id, user_message, mode, anchor,
            enabled_models, context_content, session,
            context_mode=context_mode, selected_topics=selected_topics,
        ):
            yield event
        return

    # Auto-compact if needed
    compact_stats = await _auto_compact_if_needed(conversation_id, session)
    if compact_stats and not compact_stats.get("skipped") and not compact_stats.get("error"):
        yield _sse({"type": "compaction", **compact_stats})

    history = _load_conversation_history(conversation_id, session)
    history.append({"role": "user", "model": "user", "name": "Jack", "content": user_message})

    resolved_context, loaded_topics = _resolve_context(
        user_message, history, context_mode, selected_topics, session,
    )
    effective_context = resolved_context if resolved_context is not None else context_content
    yield _sse({"type": "context_loaded", "topics": loaded_topics})

    # Assign roles
    if debate_roles:
        proposer_keys = [k for k in order if debate_roles.get(k) == "proposer"]
        critic_keys = [k for k in order if debate_roles.get(k) == "critic"]
        synth_keys = [k for k in order if debate_roles.get(k) == "synthesizer"]
        if len(proposer_keys) >= 1 and len(synth_keys) >= 1:
            critic_key = critic_keys[0] if critic_keys else None
            arbiter_key = synth_keys[0]
        else:
            debate_roles = None

    if not debate_roles:
        proposer_keys = [order[0], order[2]] if len(order) >= 4 else [order[0]]
        critic_key = order[1]
        arbiter_key = order[-1]

    # --- Phase 1: Proposals in parallel ---
    event_queue: asyncio.Queue[str | None] = asyncio.Queue()
    proposals: dict[str, dict] = {}

    async def _stream_proposal(model_key: str):
        config = models[model_key]
        client = CLIENTS[config.provider]
        system_prompt = build_system_prompt(
            effective_context, mode, config.display_name, protocol="blind",
        )

        await event_queue.put(_sse({
            "type": "model_start", "model": model_key, "name": config.display_name,
            "protocol_role": "proposal",
        }))

        try:
            formatted = client.format_history(history, model_key)
            full_response = ""
            stream = client.call_stream(formatted, config, system_prompt)
            async for delta in stream:
                full_response += delta
                await event_queue.put(_sse({"type": "token", "model": model_key, "delta": delta}))

            thinking_content = getattr(stream, "thinking_content", None)
            proposals[model_key] = {"content": full_response, "thinking": thinking_content}

            _save_msg(session, conversation_id, model_key, config.display_name,
                      full_response, thinking_content=thinking_content, protocol_role="proposal")

            await event_queue.put(_sse({
                "type": "model_done", "model": model_key, "content": full_response,
                "protocol_role": "proposal",
            }))

        except Exception as e:
            error_msg = str(e)
            proposals[model_key] = {"content": f"⚠ Error: {error_msg}", "thinking": None}
            await event_queue.put(_sse({"type": "model_error", "model": model_key, "error": error_msg}))
            _save_msg(session, conversation_id, model_key, config.display_name,
                      f"⚠ Error: {error_msg}", is_error=True, protocol_role="proposal")

    tasks = [asyncio.create_task(_stream_proposal(k)) for k in proposer_keys]

    async def _monitor():
        await asyncio.gather(*tasks)
        await event_queue.put(None)

    monitor = asyncio.create_task(_monitor())

    while True:
        event = await event_queue.get()
        if event is None:
            break
        yield event

    await monitor

    # --- Phase 2: Critic reviews proposals (anonymized) ---
    critique_content = ""
    if critic_key:
        critic_config = models[critic_key]
        critic_client = CLIENTS[critic_config.provider]

        proposal_sections = []
        for i, pk in enumerate(proposer_keys):
            p_content = proposals.get(pk, {}).get("content", "(no response)")
            proposal_sections.append(f"**Proposal {i+1}:**\n{p_content}")

        critic_input = (
            f"Original prompt from Jack: {user_message}\n\n"
            + "\n\n---\n\n".join(proposal_sections)
        )

        critic_system = build_system_prompt(
            effective_context, mode, critic_config.display_name,
            protocol="debate", protocol_role_prompt=PROTOCOL_PROMPTS["critic"],
        )

        yield _sse({
            "type": "model_start", "model": critic_key, "name": critic_config.display_name,
            "protocol_role": "critic",
        })

        try:
            critic_history = history + [{
                "role": "user", "model": "user", "name": "Jack", "content": critic_input,
            }]
            formatted = critic_client.format_history(critic_history, critic_key)

            stream = critic_client.call_stream(formatted, critic_config, critic_system)
            async for delta in stream:
                critique_content += delta
                yield _sse({"type": "token", "model": critic_key, "delta": delta})

            thinking_content = getattr(stream, "thinking_content", None)

            _save_msg(session, conversation_id, critic_key, critic_config.display_name,
                      critique_content, thinking_content=thinking_content, protocol_role="critic")

            yield _sse({
                "type": "model_done", "model": critic_key, "content": critique_content,
                "protocol_role": "critic",
            })

        except Exception as e:
            error_msg = str(e)
            yield _sse({"type": "model_error", "model": critic_key, "error": error_msg})
            _save_msg(session, conversation_id, critic_key, critic_config.display_name,
                      f"⚠ Error: {error_msg}", is_error=True, protocol_role="critic")

    # --- Phase 3: Synthesizer arbitrates with full attribution ---
    arbiter_config = models[arbiter_key]
    arbiter_client = CLIENTS[arbiter_config.provider]

    proposer_names = [models[pk].display_name for pk in proposer_keys]
    critic_name = models[critic_key].display_name if critic_key else "N/A"

    arbiter_role_prompt = PROTOCOL_PROMPTS["arbiter"].format(
        proposer1_name=proposer_names[0],
        proposer2_name=proposer_names[1] if len(proposer_names) > 1 else proposer_names[0],
        critic_name=critic_name,
    )

    arbiter_parts = [f"Original prompt from Jack: {user_message}"]
    for i, pk in enumerate(proposer_keys):
        p_content = proposals.get(pk, {}).get("content", "(no response)")
        arbiter_parts.append(f"**Proposal {i+1}** (from {models[pk].display_name}):\n{p_content}")
    if critique_content:
        arbiter_parts.append(f"**Critique** (from {critic_name}):\n{critique_content}")
    arbiter_input = "\n\n---\n\n".join(arbiter_parts)

    arbiter_system = build_system_prompt(
        effective_context, mode, arbiter_config.display_name,
        protocol="debate", protocol_role_prompt=arbiter_role_prompt,
    )

    yield _sse({
        "type": "model_start", "model": arbiter_key, "name": arbiter_config.display_name,
        "protocol_role": "synthesis",
    })

    try:
        arbiter_history = history + [{
            "role": "user", "model": "user", "name": "Jack", "content": arbiter_input,
        }]
        formatted = arbiter_client.format_history(arbiter_history, arbiter_key)

        full_response = ""
        stream = arbiter_client.call_stream(formatted, arbiter_config, arbiter_system)
        async for delta in stream:
            full_response += delta
            yield _sse({"type": "token", "model": arbiter_key, "delta": delta})

        thinking_content = getattr(stream, "thinking_content", None)

        _save_msg(session, conversation_id, arbiter_key, arbiter_config.display_name,
                  full_response, thinking_content=thinking_content,
                  protocol_role="synthesis", trust_tier="derived")

        yield _sse({
            "type": "model_done", "model": arbiter_key, "content": full_response,
            "protocol_role": "synthesis",
        })

    except Exception as e:
        error_msg = str(e)
        yield _sse({"type": "model_error", "model": arbiter_key, "error": error_msg})
        _save_msg(session, conversation_id, arbiter_key, arbiter_config.display_name,
                  f"⚠ Error: {error_msg}", is_error=True, protocol_role="synthesis")

    ctx_tokens = estimate_tokens(history)
    yield _sse({"type": "round_done", "context_tokens": ctx_tokens, "context_limit": 30000})


# ============================================================
# HELPERS
# ============================================================

def _load_conversation_history(conversation_id: int, session: Session) -> list[dict]:
    """Load prior messages excluding compacted ones (compaction summaries included)."""
    messages = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .where(Message.compacted == False)  # noqa: E712
        .order_by(Message.created_at)  # type: ignore
    ).all()

    return [
        {
            "role": m.role,
            "model": m.model,
            "name": m.name,
            "content": m.content,
        }
        for m in messages
    ]


async def _auto_compact_if_needed(conversation_id: int, session: Session) -> dict | None:
    """Check context pressure and auto-compact if over threshold. Returns stats or None."""
    messages = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .where(Message.compacted == False)  # noqa: E712
        .order_by(Message.created_at)  # type: ignore
    ).all()

    if should_compact(messages):
        logger.info("Auto-compacting conversation %d (est. %d tokens)", conversation_id, estimate_tokens(messages))
        return await compact_conversation(session, conversation_id)
    return None


def _save_msg(session, conversation_id, model_key, display_name, content,
               thinking_content=None, protocol_role=None, is_error=False,
               trust_tier="model"):
    """Create and save a Message with provenance fields."""
    msg = Message(
        conversation_id=conversation_id,
        role="assistant",
        model=model_key,
        name=display_name,
        content=content,
        thinking_content=thinking_content,
        protocol_role=protocol_role,
        is_error=is_error,
        source=model_key,
        trust_tier="system" if is_error else trust_tier,
    )
    session.add(msg)
    session.commit()
    return msg


def _sse(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data)}\n\n"
