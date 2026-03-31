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

Future protocols / features:
  TODO: Forced Dissent mode — inject "you MUST disagree with at least one prior response"
        into the system prompt when enabled. Toggle in UI alongside protocol selector.
  TODO: Divergence Heatmap — track semantic similarity between model responses per round.
        Store divergence scores in Message or a new AnalyticsEvent table. Frontend renders
        a color-coded heatmap grid showing where models agree/disagree.
  TODO: Chain-of-Thought Leakage Monitor — detect when thinking_content themes bleed into
        the visible response (e.g. model references its own internal reasoning). Flag these
        in the UI with a warning badge on the message.
"""
import json
import asyncio
from typing import AsyncGenerator
from sqlmodel import Session, select

from ..config import get_active_config, ModelConfig
from ..models import Message, Conversation
from ..context import build_system_prompt, PROTOCOL_PROMPTS
from . import claude, openai_client, gemini, grok

# Map provider names to client modules
CLIENTS = {
    "anthropic": claude,
    "openai": openai_client,
    "gemini": gemini,
    "grok": grok,
}


# ============================================================
# ROUNDTABLE PROTOCOL (existing behavior)
# ============================================================

async def run_round(
    conversation_id: int,
    user_message: str,
    mode: str,
    anchor: str,
    enabled_models: list[str],
    context_content: str,
    session: Session,
) -> AsyncGenerator[str, None]:
    """
    Execute a full round-robin and yield SSE events.

    SSE event format:
    - data: {"type": "model_start", "model": "claude", "name": "Claude Sonnet 4.6"}
    - data: {"type": "token", "model": "claude", "delta": "Hello"}
    - data: {"type": "model_done", "model": "claude", "content": "full response"}
    - data: {"type": "model_error", "model": "claude", "error": "timeout"}
    - data: {"type": "round_done"}
    """
    models, order = get_active_config(mode, anchor, enabled_models)

    # Accumulate messages for this round (user + each model's response)
    round_messages = _load_conversation_history(conversation_id, session)
    round_messages.append({
        "role": "user",
        "model": "user",
        "name": "Jack",
        "content": user_message,
    })

    for model_key in order:
        config = models[model_key]
        client = CLIENTS[config.provider]
        system_prompt = build_system_prompt(context_content, mode, config.display_name)

        # Signal model starting
        yield _sse({"type": "model_start", "model": model_key, "name": config.display_name})

        try:
            # Format history for this specific model's API format
            formatted = client.format_history(round_messages, model_key)

            # Stream response
            full_response = ""
            stream = client.call_stream(formatted, config, system_prompt)
            async for delta in stream:
                full_response += delta
                yield _sse({"type": "token", "model": model_key, "delta": delta})

            # Capture thinking/reasoning content if the provider exposes it
            thinking_content = getattr(stream, "thinking_content", None)

            # Save to DB
            # TODO: Export thinking_content for chain-of-thought visualization and debugging UI
            msg = Message(
                conversation_id=conversation_id,
                role="assistant",
                model=model_key,
                name=config.display_name,
                content=full_response,
                thinking_content=thinking_content,
            )
            session.add(msg)
            session.commit()

            # Add to round history so next model sees it
            round_messages.append({
                "role": "assistant",
                "model": model_key,
                "name": config.display_name,
                "content": full_response,
            })

            yield _sse({"type": "model_done", "model": model_key, "content": full_response})

        except Exception as e:
            error_msg = str(e)
            yield _sse({"type": "model_error", "model": model_key, "error": error_msg})

            # Save error as message so it shows in history
            msg = Message(
                conversation_id=conversation_id,
                role="assistant",
                model=model_key,
                name=config.display_name,
                content=f"⚠ Error: {error_msg}",
                is_error=True,
            )
            session.add(msg)
            session.commit()

    yield _sse({"type": "round_done"})


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
) -> AsyncGenerator[str, None]:
    """
    All models answer independently in parallel (blind), then the anchor synthesizes.
    Tokens stream as they arrive from each model concurrently.
    """
    models, order = get_active_config(mode, anchor, enabled_models)

    if len(order) < 2:
        # Need at least 2 models for blind protocol — fall back to roundtable
        async for event in run_round(
            conversation_id, user_message, mode, anchor,
            enabled_models, context_content, session,
        ):
            yield event
        return

    history = _load_conversation_history(conversation_id, session)
    history.append({
        "role": "user", "model": "user", "name": "Jack", "content": user_message,
    })

    # Split: non-anchor models answer independently, anchor synthesizes
    independent_keys = order[:-1]
    anchor_key = order[-1]

    # Queue for streaming SSE events from parallel tasks
    event_queue: asyncio.Queue[str | None] = asyncio.Queue()
    results: dict[str, dict] = {}  # model_key -> {"content": str, "thinking": str|None, "error": bool}

    async def _stream_model(model_key: str):
        """Stream a single model's response, pushing SSE events to the shared queue."""
        config = models[model_key]
        client = CLIENTS[config.provider]
        system_prompt = build_system_prompt(
            context_content, mode, config.display_name, protocol="blind",
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

            # Save to DB
            msg = Message(
                conversation_id=conversation_id,
                role="assistant",
                model=model_key,
                name=config.display_name,
                content=full_response,
                thinking_content=thinking_content,
                protocol_role="proposal",
            )
            session.add(msg)
            session.commit()

            await event_queue.put(_sse({
                "type": "model_done", "model": model_key, "content": full_response,
                "protocol_role": "proposal",
            }))

        except Exception as e:
            error_msg = str(e)
            results[model_key] = {"content": f"⚠ Error: {error_msg}", "thinking": None, "error": True}
            await event_queue.put(_sse({"type": "model_error", "model": model_key, "error": error_msg}))
            msg = Message(
                conversation_id=conversation_id, role="assistant", model=model_key,
                name=config.display_name, content=f"⚠ Error: {error_msg}",
                is_error=True, protocol_role="proposal",
            )
            session.add(msg)
            session.commit()

    # Run all independent models in parallel
    tasks = [asyncio.create_task(_stream_model(k)) for k in independent_keys]

    # Drain events as they arrive until all tasks complete
    done_count = 0
    total = len(tasks)

    async def _monitor():
        await asyncio.gather(*tasks)
        await event_queue.put(None)  # sentinel

    monitor = asyncio.create_task(_monitor())

    while True:
        event = await event_queue.get()
        if event is None:
            break
        yield event

    await monitor  # ensure cleanup

    # Now run the anchor with synthesis prompt
    anchor_config = models[anchor_key]
    anchor_client = CLIENTS[anchor_config.provider]

    # Build synthesis input: all independent responses bundled
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
        context_content, mode, anchor_config.display_name,
        protocol="blind",
        protocol_role_prompt=PROTOCOL_PROMPTS["synthesis"],
    )

    yield _sse({
        "type": "model_start", "model": anchor_key, "name": anchor_config.display_name,
        "protocol_role": "synthesis",
    })

    try:
        # Build history with synthesis input as a user message
        synth_history = history + [{
            "role": "user", "model": "user", "name": "Jack",
            "content": synthesis_input,
        }]
        formatted = anchor_client.format_history(synth_history, anchor_key)

        full_response = ""
        stream = anchor_client.call_stream(formatted, anchor_config, synthesis_system)
        async for delta in stream:
            full_response += delta
            yield _sse({"type": "token", "model": anchor_key, "delta": delta})

        thinking_content = getattr(stream, "thinking_content", None)

        msg = Message(
            conversation_id=conversation_id, role="assistant", model=anchor_key,
            name=anchor_config.display_name, content=full_response,
            thinking_content=thinking_content, protocol_role="synthesis",
        )
        session.add(msg)
        session.commit()

        yield _sse({
            "type": "model_done", "model": anchor_key, "content": full_response,
            "protocol_role": "synthesis",
        })

    except Exception as e:
        error_msg = str(e)
        yield _sse({"type": "model_error", "model": anchor_key, "error": error_msg})
        msg = Message(
            conversation_id=conversation_id, role="assistant", model=anchor_key,
            name=anchor_config.display_name, content=f"⚠ Error: {error_msg}",
            is_error=True, protocol_role="synthesis",
        )
        session.add(msg)
        session.commit()

    yield _sse({"type": "round_done"})


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
) -> AsyncGenerator[str, None]:
    """
    Debate protocol:
    1. Proposers answer independently (parallel, blind)
    2. Critic reviews both proposals (anonymized — no model names)
    3. Synthesizer arbitrates with full attribution restored

    Roles can be explicitly assigned via debate_roles dict, or inferred
    from position (first=proposer, second=critic, third=proposer, last=synthesizer).

    Requires at least 3 models. Falls back to blind with <3, roundtable with <2.
    """
    models, order = get_active_config(mode, anchor, enabled_models)

    if len(order) < 3:
        # Not enough models for debate — fall back
        fallback = run_blind if len(order) >= 2 else run_round
        async for event in fallback(
            conversation_id, user_message, mode, anchor,
            enabled_models, context_content, session,
        ):
            yield event
        return

    history = _load_conversation_history(conversation_id, session)
    history.append({
        "role": "user", "model": "user", "name": "Jack", "content": user_message,
    })

    # Assign roles from debate_roles dict or fall back to position-based
    if debate_roles:
        proposer_keys = [k for k in order if debate_roles.get(k) == "proposer"]
        critic_keys = [k for k in order if debate_roles.get(k) == "critic"]
        synth_keys = [k for k in order if debate_roles.get(k) == "synthesizer"]
        # Validate: need at least 1 proposer, 1 critic or 0, 1 synthesizer
        if len(proposer_keys) >= 1 and len(synth_keys) >= 1:
            critic_key = critic_keys[0] if critic_keys else None
            arbiter_key = synth_keys[0]
        else:
            # Invalid roles, fall back to position-based
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
            context_content, mode, config.display_name, protocol="blind",
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

            msg = Message(
                conversation_id=conversation_id, role="assistant", model=model_key,
                name=config.display_name, content=full_response,
                thinking_content=thinking_content, protocol_role="proposal",
            )
            session.add(msg)
            session.commit()

            await event_queue.put(_sse({
                "type": "model_done", "model": model_key, "content": full_response,
                "protocol_role": "proposal",
            }))

        except Exception as e:
            error_msg = str(e)
            proposals[model_key] = {"content": f"⚠ Error: {error_msg}", "thinking": None}
            await event_queue.put(_sse({"type": "model_error", "model": model_key, "error": error_msg}))
            msg = Message(
                conversation_id=conversation_id, role="assistant", model=model_key,
                name=config.display_name, content=f"⚠ Error: {error_msg}",
                is_error=True, protocol_role="proposal",
            )
            session.add(msg)
            session.commit()

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

        # Build anonymized proposal list
        proposal_sections = []
        for i, pk in enumerate(proposer_keys):
            p_content = proposals.get(pk, {}).get("content", "(no response)")
            proposal_sections.append(f"**Proposal {i+1}:**\n{p_content}")

        critic_input = (
            f"Original prompt from Jack: {user_message}\n\n"
            + "\n\n---\n\n".join(proposal_sections)
        )

        critic_system = build_system_prompt(
            context_content, mode, critic_config.display_name,
            protocol="debate",
            protocol_role_prompt=PROTOCOL_PROMPTS["critic"],
        )

        yield _sse({
            "type": "model_start", "model": critic_key, "name": critic_config.display_name,
            "protocol_role": "critic",
        })

        try:
            critic_history = history + [{
                "role": "user", "model": "user", "name": "Jack",
                "content": critic_input,
            }]
            formatted = critic_client.format_history(critic_history, critic_key)

            stream = critic_client.call_stream(formatted, critic_config, critic_system)
            async for delta in stream:
                critique_content += delta
                yield _sse({"type": "token", "model": critic_key, "delta": delta})

            thinking_content = getattr(stream, "thinking_content", None)

            msg = Message(
                conversation_id=conversation_id, role="assistant", model=critic_key,
                name=critic_config.display_name, content=critique_content,
                thinking_content=thinking_content, protocol_role="critic",
            )
            session.add(msg)
            session.commit()

            yield _sse({
                "type": "model_done", "model": critic_key, "content": critique_content,
                "protocol_role": "critic",
            })

        except Exception as e:
            error_msg = str(e)
            yield _sse({"type": "model_error", "model": critic_key, "error": error_msg})
            msg = Message(
                conversation_id=conversation_id, role="assistant", model=critic_key,
                name=critic_config.display_name, content=f"⚠ Error: {error_msg}",
                is_error=True, protocol_role="critic",
            )
            session.add(msg)
            session.commit()

    # --- Phase 3: Synthesizer arbitrates with full attribution ---
    arbiter_config = models[arbiter_key]
    arbiter_client = CLIENTS[arbiter_config.provider]

    # Build attribution strings for the arbiter prompt
    proposer_names = [models[pk].display_name for pk in proposer_keys]
    critic_name = models[critic_key].display_name if critic_key else "N/A"

    arbiter_role_prompt = PROTOCOL_PROMPTS["arbiter"].format(
        proposer1_name=proposer_names[0],
        proposer2_name=proposer_names[1] if len(proposer_names) > 1 else proposer_names[0],
        critic_name=critic_name,
    )

    # Build arbiter input with full attribution restored
    arbiter_parts = [f"Original prompt from Jack: {user_message}"]
    for i, pk in enumerate(proposer_keys):
        p_content = proposals.get(pk, {}).get("content", "(no response)")
        arbiter_parts.append(f"**Proposal {i+1}** (from {models[pk].display_name}):\n{p_content}")
    if critique_content:
        arbiter_parts.append(f"**Critique** (from {critic_name}):\n{critique_content}")
    arbiter_input = "\n\n---\n\n".join(arbiter_parts)

    arbiter_system = build_system_prompt(
        context_content, mode, arbiter_config.display_name,
        protocol="debate",
        protocol_role_prompt=arbiter_role_prompt,
    )

    yield _sse({
        "type": "model_start", "model": arbiter_key, "name": arbiter_config.display_name,
        "protocol_role": "synthesis",
    })

    try:
        arbiter_history = history + [{
            "role": "user", "model": "user", "name": "Jack",
            "content": arbiter_input,
        }]
        formatted = arbiter_client.format_history(arbiter_history, arbiter_key)

        full_response = ""
        stream = arbiter_client.call_stream(formatted, arbiter_config, arbiter_system)
        async for delta in stream:
            full_response += delta
            yield _sse({"type": "token", "model": arbiter_key, "delta": delta})

        thinking_content = getattr(stream, "thinking_content", None)

        msg = Message(
            conversation_id=conversation_id, role="assistant", model=arbiter_key,
            name=arbiter_config.display_name, content=full_response,
            thinking_content=thinking_content, protocol_role="synthesis",
        )
        session.add(msg)
        session.commit()

        yield _sse({
            "type": "model_done", "model": arbiter_key, "content": full_response,
            "protocol_role": "synthesis",
        })

    except Exception as e:
        error_msg = str(e)
        yield _sse({"type": "model_error", "model": arbiter_key, "error": error_msg})
        msg = Message(
            conversation_id=conversation_id, role="assistant", model=arbiter_key,
            name=arbiter_config.display_name, content=f"⚠ Error: {error_msg}",
            is_error=True, protocol_role="synthesis",
        )
        session.add(msg)
        session.commit()

    yield _sse({"type": "round_done"})


# ============================================================
# HELPERS
# ============================================================

def _load_conversation_history(conversation_id: int, session: Session) -> list[dict]:
    """Load all prior messages in this conversation as dicts."""
    messages = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation_id)
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


def _sse(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data)}\n\n"
