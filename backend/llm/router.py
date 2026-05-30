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
import dataclasses
from typing import AsyncGenerator
from sqlmodel import Session, select

from ..config import get_active_config, ModelConfig, SessionConfig
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


def _apply_overrides(
    models: dict[str, ModelConfig],
    overrides: dict | None
) -> dict[str, ModelConfig]:
    """Apply runtime settings overrides from the frontend to ModelConfig objects."""
    if not overrides:
        return models

    updated_models = {}
    for model_key, config in models.items():
        if model_key in overrides and overrides[model_key]:
            model_overrides = overrides[model_key]
            valid_fields = {}
            for field_name in dataclasses.fields(ModelConfig):
                if field_name.name in model_overrides:
                    valid_fields[field_name.name] = model_overrides[field_name.name]
            
            # Create a new config with the overridden fields
            updated_models[model_key] = dataclasses.replace(config, **valid_fields)
        else:
            updated_models[model_key] = config
    return updated_models



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
    config: SessionConfig,
    context_content: str,
    session: Session,
    model_overrides: dict | None = None,
) -> AsyncGenerator[str, None]:
    """
    Execute a full roundtable and yield SSE events.
    """
    # 1. Routing classification and selection
    active_participants = config.participants
    category = "writing"
    if config.routing_enabled:
        from ..routing.classifier import classify_prompt
        from ..routing.selector import select_models
        
        classification = await classify_prompt(user_message)
        category = classification.get("category", "writing")
        complexity = classification.get("complexity", "medium")
        explanation = classification.get("explanation", "")
        
        selected_keys, rationale = select_models(
            session=session,
            category=category,
            mode=config.mode,
            anchor_mode=config.anchor,
            enabled_models=config.participants
        )
        active_participants = selected_keys
        
        yield _sse({
            "type": "routing_chosen",
            "category": category,
            "complexity": complexity,
            "explanation": explanation,
            "selected_models": selected_keys,
            "rationale": rationale
        })

    models, order = get_active_config(config.mode, config.anchor, active_participants)
    models = _apply_overrides(models, model_overrides)

    # Auto-compact if context pressure is high
    compact_stats = await _auto_compact_if_needed(conversation_id, session)
    if compact_stats and not compact_stats.get("skipped") and not compact_stats.get("error"):
        yield _sse({"type": "compaction", **compact_stats})

    # Accumulate messages for this round (user + each model's response)
    round_messages = _load_conversation_history(conversation_id, session)
    if not round_messages or not (round_messages[-1]["role"] == "user" and round_messages[-1]["content"] == user_message):
        round_messages.append({
            "role": "user", "model": "user", "name": "Jack", "content": user_message,
        })

    # Resolve context via memory-as-hint system
    resolved_context, loaded_topics = _resolve_context(
        user_message, round_messages, config.context_mode, config.selected_topics, session,
    )
    effective_context = resolved_context if resolved_context is not None else context_content

    yield _sse({"type": "context_loaded", "topics": loaded_topics})

    proposals_dict = {}
    synthesis_content = ""

    for model_key in order:
        model_config = models[model_key]
        client = CLIENTS[model_config.provider]
        system_prompt = build_system_prompt(
            effective_context, config.mode, model_config.display_name, forced_dissent=config.forced_dissent
        )

        yield _sse({"type": "model_start", "model": model_key, "name": model_config.display_name})

        try:
            formatted = client.format_history(round_messages, model_key)
            full_response = ""
            stream = client.call_stream(formatted, model_config, system_prompt)
            async for is_thinking, delta in _read_stream(stream):
                if is_thinking:
                    yield _sse({"type": "thinking_token", "model": model_key, "delta": delta})
                else:
                    full_response += delta
                    yield _sse({"type": "token", "model": model_key, "delta": delta})

            thinking_content = getattr(stream, "thinking_content", None)

            _save_msg(session, conversation_id, model_key, model_config.display_name,
                      full_response, thinking_content=thinking_content)

            round_messages.append({
                "role": "assistant", "model": model_key,
                "name": model_config.display_name, "content": full_response,
            })

            if model_key != order[-1]:
                proposals_dict[model_key] = full_response
            else:
                synthesis_content = full_response

            yield _sse({"type": "model_done", "model": model_key, "content": full_response})

        except Exception as e:
            error_msg = str(e)
            logger.error("Model %s failed: %s", model_key, error_msg, exc_info=True)
            err_details = _format_provider_error(e)
            yield _sse({
                "type": "model_error",
                "model": model_key,
                "error": error_msg,
                "error_details": err_details
            })

            _save_msg(session, conversation_id, model_key, model_config.display_name,
                      f"⚠ Error: {error_msg}", is_error=True)

    # Post-round outcome evaluator trigger
    if config.routing_enabled and len(order) >= 2 and synthesis_content and proposals_dict:
        from ..database import engine
        from sqlmodel import Session as SQLSession
        from ..routing.ledger import evaluate_and_log_outcomes
        
        async def run_eval_bg():
            with SQLSession(engine) as bg_session:
                await evaluate_and_log_outcomes(
                    session=bg_session,
                    conversation_id=conversation_id,
                    category=category,
                    user_message=user_message,
                    proposals=proposals_dict,
                    synthesis_content=synthesis_content
                )
        asyncio.create_task(run_eval_bg())

    ctx_tokens = estimate_tokens(round_messages)
    yield _sse({"type": "round_done", "context_tokens": ctx_tokens, "context_limit": 30000})


# ============================================================
# BLIND → SYNTHESIS PROTOCOL
# ============================================================

async def run_blind(
    conversation_id: int,
    user_message: str,
    config: SessionConfig,
    context_content: str,
    session: Session,
    model_overrides: dict | None = None,
) -> AsyncGenerator[str, None]:
    """All models answer independently in parallel (blind), then the anchor synthesizes."""
    # 1. Routing classification and selection
    active_participants = config.participants
    category = "writing"
    if config.routing_enabled:
        from ..routing.classifier import classify_prompt
        from ..routing.selector import select_models
        
        classification = await classify_prompt(user_message)
        category = classification.get("category", "writing")
        complexity = classification.get("complexity", "medium")
        explanation = classification.get("explanation", "")
        
        selected_keys, rationale = select_models(
            session=session,
            category=category,
            mode=config.mode,
            anchor_mode=config.anchor,
            enabled_models=config.participants
        )
        active_participants = selected_keys
        
        yield _sse({
            "type": "routing_chosen",
            "category": category,
            "complexity": complexity,
            "explanation": explanation,
            "selected_models": selected_keys,
            "rationale": rationale
        })

    models, order = get_active_config(config.mode, config.anchor, active_participants)
    models = _apply_overrides(models, model_overrides)

    if len(order) < 2:
        async for event in run_round(
            conversation_id=conversation_id,
            user_message=user_message,
            config=config,
            context_content=context_content,
            session=session,
            model_overrides=model_overrides,
        ):
            yield event
        return

    # Auto-compact if needed
    compact_stats = await _auto_compact_if_needed(conversation_id, session)
    if compact_stats and not compact_stats.get("skipped") and not compact_stats.get("error"):
        yield _sse({"type": "compaction", **compact_stats})

    history = _load_conversation_history(conversation_id, session)
    if not history or not (history[-1]["role"] == "user" and history[-1]["content"] == user_message):
        history.append({"role": "user", "model": "user", "name": "Jack", "content": user_message})

    resolved_context, loaded_topics = _resolve_context(
        user_message, history, config.context_mode, config.selected_topics, session,
    )
    effective_context = resolved_context if resolved_context is not None else context_content
    yield _sse({"type": "context_loaded", "topics": loaded_topics})

    independent_keys = order[:-1]
    anchor_key = order[-1]

    event_queue: asyncio.Queue[str | None] = asyncio.Queue()
    results: dict[str, dict] = {}

    async def _stream_model(model_key: str):
        model_config = models[model_key]
        client = CLIENTS[model_config.provider]
        system_prompt = build_system_prompt(
            effective_context, config.mode, model_config.display_name, protocol="blind",
            forced_dissent=config.forced_dissent,
        )

        await event_queue.put(_sse({
            "type": "model_start", "model": model_key, "name": model_config.display_name,
            "protocol_role": "proposal",
        }))

        try:
            formatted = client.format_history(history, model_key)
            full_response = ""
            stream = client.call_stream(formatted, model_config, system_prompt)
            async for is_thinking, delta in _read_stream(stream):
                if is_thinking:
                    await event_queue.put(_sse({"type": "thinking_token", "model": model_key, "delta": delta}))
                else:
                    full_response += delta
                    await event_queue.put(_sse({"type": "token", "model": model_key, "delta": delta}))

            thinking_content = getattr(stream, "thinking_content", None)
            results[model_key] = {"content": full_response, "thinking": thinking_content, "error": False}

            _save_msg(session, conversation_id, model_key, model_config.display_name,
                      full_response, thinking_content=thinking_content, protocol_role="proposal")

            await event_queue.put(_sse({
                "type": "model_done", "model": model_key, "content": full_response,
                "protocol_role": "proposal",
            }))

        except Exception as e:
            error_msg = str(e)
            results[model_key] = {"content": f"⚠ Error: {error_msg}", "thinking": None, "error": True}
            err_details = _format_provider_error(e)
            await event_queue.put(_sse({
                "type": "model_error",
                "model": model_key,
                "error": error_msg,
                "error_details": err_details
            }))
            _save_msg(session, conversation_id, model_key, model_config.display_name,
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

    # Map database logic back to display names
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
        effective_context, config.mode, anchor_config.display_name,
        protocol="blind", protocol_role_prompt=PROTOCOL_PROMPTS["synthesis"],
        forced_dissent=config.forced_dissent,
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
        async for is_thinking, delta in _read_stream(stream):
            if is_thinking:
                yield _sse({"type": "thinking_token", "model": anchor_key, "delta": delta})
            else:
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
        err_details = _format_provider_error(e)
        yield _sse({
            "type": "model_error",
            "model": anchor_key,
            "error": error_msg,
            "error_details": err_details
        })
        _save_msg(session, conversation_id, anchor_key, anchor_config.display_name,
                  f"⚠ Error: {error_msg}", is_error=True, protocol_role="synthesis")

    # Post-round outcome evaluator trigger
    if config.routing_enabled and len(order) >= 2:
        proposals_dict = {k: r["content"] for k, r in results.items() if k != order[-1] and not r.get("error")}
        synthesis_content = full_response
        if proposals_dict and synthesis_content:
            from ..database import engine
            from sqlmodel import Session as SQLSession
            from ..routing.ledger import evaluate_and_log_outcomes
            
            async def run_eval_bg():
                with SQLSession(engine) as bg_session:
                    await evaluate_and_log_outcomes(
                        session=bg_session,
                        conversation_id=conversation_id,
                        category=category,
                        user_message=user_message,
                        proposals=proposals_dict,
                        synthesis_content=synthesis_content
                    )
            asyncio.create_task(run_eval_bg())

    ctx_tokens = estimate_tokens(history)
    yield _sse({"type": "round_done", "context_tokens": ctx_tokens, "context_limit": 30000})


# ============================================================
# DEBATE PROTOCOL
# ============================================================

async def run_debate(
    conversation_id: int,
    user_message: str,
    config: SessionConfig,
    context_content: str,
    session: Session,
    debate_roles: dict[str, str] | None = None,
    model_overrides: dict | None = None,
) -> AsyncGenerator[str, None]:
    """
    Debate protocol: proposers → critic (anonymized) → arbiter (full attribution).
    """
    # 1. Routing classification and selection
    active_participants = config.participants
    category = "writing"
    if config.routing_enabled:
        from ..routing.classifier import classify_prompt
        from ..routing.selector import select_models
        
        classification = await classify_prompt(user_message)
        category = classification.get("category", "writing")
        complexity = classification.get("complexity", "medium")
        explanation = classification.get("explanation", "")
        
        selected_keys, rationale = select_models(
            session=session,
            category=category,
            mode=config.mode,
            anchor_mode=config.anchor,
            enabled_models=config.participants
        )
        active_participants = selected_keys
        
        yield _sse({
            "type": "routing_chosen",
            "category": category,
            "complexity": complexity,
            "explanation": explanation,
            "selected_models": selected_keys,
            "rationale": rationale
        })

    models, order = get_active_config(config.mode, config.anchor, active_participants)
    models = _apply_overrides(models, model_overrides)

    if len(order) < 3:
        fallback = run_blind if len(order) >= 2 else run_round
        async for event in fallback(
            conversation_id=conversation_id,
            user_message=user_message,
            config=config,
            context_content=context_content,
            session=session,
            model_overrides=model_overrides,
        ):
            yield event
        return

    # Auto-compact if needed
    compact_stats = await _auto_compact_if_needed(conversation_id, session)
    if compact_stats and not compact_stats.get("skipped") and not compact_stats.get("error"):
        yield _sse({"type": "compaction", **compact_stats})

    history = _load_conversation_history(conversation_id, session)
    if not history or not (history[-1]["role"] == "user" and history[-1]["content"] == user_message):
        history.append({"role": "user", "model": "user", "name": "Jack", "content": user_message})

    resolved_context, loaded_topics = _resolve_context(
        user_message, history, config.context_mode, config.selected_topics, session,
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
        model_config = models[model_key]
        client = CLIENTS[model_config.provider]
        system_prompt = build_system_prompt(
            effective_context, config.mode, model_config.display_name, protocol="blind",
            forced_dissent=config.forced_dissent,
        )

        await event_queue.put(_sse({
            "type": "model_start", "model": model_key, "name": model_config.display_name,
            "protocol_role": "proposal",
        }))

        try:
            formatted = client.format_history(history, model_key)
            full_response = ""
            stream = client.call_stream(formatted, model_config, system_prompt)
            async for is_thinking, delta in _read_stream(stream):
                if is_thinking:
                    await event_queue.put(_sse({"type": "thinking_token", "model": model_key, "delta": delta}))
                else:
                    full_response += delta
                    await event_queue.put(_sse({"type": "token", "model": model_key, "delta": delta}))

            thinking_content = getattr(stream, "thinking_content", None)
            proposals[model_key] = {"content": full_response, "thinking": thinking_content}

            _save_msg(session, conversation_id, model_key, model_config.display_name,
                      full_response, thinking_content=thinking_content, protocol_role="proposal")

            await event_queue.put(_sse({
                "type": "model_done", "model": model_key, "content": full_response,
                "protocol_role": "proposal",
            }))

        except Exception as e:
            error_msg = str(e)
            proposals[model_key] = {"content": f"⚠ Error: {error_msg}", "thinking": None}
            err_details = _format_provider_error(e)
            await event_queue.put(_sse({
                "type": "model_error",
                "model": model_key,
                "error": error_msg,
                "error_details": err_details
            }))
            _save_msg(session, conversation_id, model_key, model_config.display_name,
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
            effective_context, config.mode, critic_config.display_name,
            protocol="debate", protocol_role_prompt=PROTOCOL_PROMPTS["critic"],
            forced_dissent=config.forced_dissent,
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
            async for is_thinking, delta in _read_stream(stream):
                if is_thinking:
                    await event_queue.put(_sse({"type": "thinking_token", "model": critic_key, "delta": delta}))
                else:
                    critique_content += delta
                    await event_queue.put(_sse({"type": "token", "model": critic_key, "delta": delta}))

            thinking_content = getattr(stream, "thinking_content", None)

            _save_msg(session, conversation_id, critic_key, critic_config.display_name,
                      critique_content, thinking_content=thinking_content, protocol_role="critic")

            yield _sse({
                "type": "model_done", "model": critic_key, "content": critique_content,
                "protocol_role": "critic",
            })

        except Exception as e:
            error_msg = str(e)
            err_details = _format_provider_error(e)
            yield _sse({
                "type": "model_error",
                "model": critic_key,
                "error": error_msg,
                "error_details": err_details
            })
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
        effective_context, config.mode, arbiter_config.display_name,
        protocol="debate", protocol_role_prompt=arbiter_role_prompt,
        forced_dissent=config.forced_dissent,
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
        async for is_thinking, delta in _read_stream(stream):
            if is_thinking:
                yield _sse({"type": "thinking_token", "model": arbiter_key, "delta": delta})
            else:
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
        err_details = _format_provider_error(e)
        yield _sse({
            "type": "model_error",
            "model": arbiter_key,
            "error": error_msg,
            "error_details": err_details
        })
        _save_msg(session, conversation_id, arbiter_key, arbiter_config.display_name,
                  f"⚠ Error: {error_msg}", is_error=True, protocol_role="synthesis")

    # Post-round outcome evaluator trigger
    if config.routing_enabled and len(order) >= 2:
        proposals_dict = {k: v["content"] for k, v in proposals.items()}
        synthesis_content = full_response
        if proposals_dict and synthesis_content:
            from ..database import engine
            from sqlmodel import Session as SQLSession
            from ..routing.ledger import evaluate_and_log_outcomes
            
            async def run_eval_bg():
                with SQLSession(engine) as bg_session:
                    await evaluate_and_log_outcomes(
                        session=bg_session,
                        conversation_id=conversation_id,
                        category=category,
                        user_message=user_message,
                        proposals=proposals_dict,
                        synthesis_content=synthesis_content
                    )
            asyncio.create_task(run_eval_bg())

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


async def _read_stream(stream):
    """Yields (is_thinking, delta_text) for each chunk in the stream."""
    async for delta in stream:
        if isinstance(delta, dict):
            yield (delta["type"] == "thinking"), delta["text"]
        else:
            yield False, delta


def _format_provider_error(e: Exception) -> dict:
    """Format an LLM provider exception into structured error info for UI and metrics."""
    status = getattr(e, "status_code", getattr(e, "status", None))
    msg = getattr(e, "message", str(e))
    
    err_type = "unknown"
    if status == 429 or "rate limit" in str(e).lower():
        err_type = "rate_limit"
    elif "safety" in str(e).lower() or "filter" in str(e).lower() or "policy" in str(e).lower():
        err_type = "content_filter"
        
    return {
        "type": err_type,
        "provider_message": msg,
        "status": status
    }



