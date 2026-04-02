"""
Context engine — assembles system prompts with memory-as-hint context.

The system prompt structure for every model:
1. Group chat behavior instructions
2. Memory index (always, unless context_mode is "none")
3. Loaded topic files (relevance-detected, user-selected, or none)
4. Current mode indicator
5. Protocol role prompt (if applicable)
"""
import json
import logging
from sqlmodel import select

from ..models import ContextDoc, MemoryFile
from ..memory.relevance import detect_relevant_topics

logger = logging.getLogger("roundtable.context")


GROUP_CHAT_INSTRUCTIONS = """You are in a multi-AI roundtable group chat with a human user named Jack and other AI assistants. The conversation flows round-robin — each AI responds in turn, and everyone can see all previous messages including other AIs' responses.

Rules:
- Keep responses concise (2-4 sentences) unless Jack asks for detail.
- Be conversational and natural. Reference, agree with, disagree with, or build on what other AIs said.
- Be yourself. Have opinions. Don't be sycophantic.
- If you disagree with another AI, say so directly and explain why.
- Don't recite Jack's context back to him — just let it inform how you respond.
- You are {model_name}."""

BLIND_INSTRUCTIONS = """You are in a multi-AI roundtable with a human user named Jack and other AI assistants. In this round, each AI answers Jack's prompt independently — you cannot see what other AIs said.

Rules:
- Keep responses concise (2-4 sentences) unless Jack asks for detail.
- Be yourself. Have opinions. Don't be sycophantic.
- Don't recite Jack's context back to him — just let it inform how you respond.
- You are {model_name}."""

PROTOCOL_PROMPTS = {
    "synthesis": """You are the synthesis anchor. Below are independent responses from multiple AI models to the same prompt. Compare them, identify agreements and disagreements, and synthesize a final answer that incorporates the strongest reasoning from each.""",

    "critic": """You are the critic. Two AI models independently answered the same prompt. Their identities are hidden. Your job is to find flaws, contradictions, edge cases, and weaknesses in both proposals. Do not solve the problem yourself — only critique.""",

    "arbiter": """You are the arbiter. Proposal 1 was from {proposer1_name}. Proposal 2 was from {proposer2_name}. The critique was from {critic_name}. Review the original prompt, both proposals, and the critique. Synthesize a final answer that resolves the identified weaknesses.""",
}


def get_relevant_context(
    message: str,
    recent_messages: list[str],
    context_mode: str,
    selected_topics: list[str] | None,
    session,
) -> tuple[str, list[str]]:
    """
    Resolve which memory topics to load based on context mode.

    Returns (assembled_context_string, list_of_loaded_topic_keys).
    """
    if context_mode == "none":
        return "", []

    # Load memory index
    index_file = session.exec(
        select(MemoryFile).where(MemoryFile.key == "index")
    ).first()

    if not index_file:
        # Fallback: no memory files seeded yet, use legacy monolithic context
        logger.info("No memory files found, falling back to legacy context")
        return get_current_context(session), []

    # Determine which topics to load
    if context_mode == "select" and selected_topics:
        topic_keys = selected_topics
    else:
        # "full" mode: relevance detection
        topic_keys = detect_relevant_topics(message, recent_messages, index_file.content)

    # Load topic files from DB
    loaded_topics: list[tuple[str, str]] = []
    for key in topic_keys:
        topic = session.exec(
            select(MemoryFile).where(MemoryFile.key == key)
        ).first()
        if topic:
            loaded_topics.append((key, topic.content))

    logger.info("Context mode=%s, loaded topics: %s", context_mode, [k for k, _ in loaded_topics])

    # Assemble context string with section markers
    parts = [f"# Memory Index\n{index_file.content}"]
    for key, content in loaded_topics:
        parts.append(f"# Loaded Context: {key}\n{content}")

    assembled = "\n\n".join(parts)
    return assembled, [k for k, _ in loaded_topics]


def build_system_prompt(
    context_content: str,
    mode: str,
    model_name: str,
    protocol: str = "roundtable",
    protocol_role_prompt: str = "",
) -> str:
    """
    Build the full system prompt for a model.

    Args:
        context_content: Assembled context (from get_relevant_context or legacy)
        mode: "regular" or "overdrive"
        model_name: Display name of this model (e.g. "Claude Sonnet 4.6")
        protocol: "roundtable", "blind", or "debate"
        protocol_role_prompt: Additional role-specific prompt for synthesis/critic/arbiter
    """
    if protocol == "blind":
        instructions = BLIND_INSTRUCTIONS.format(model_name=model_name)
    else:
        instructions = GROUP_CHAT_INSTRUCTIONS.format(model_name=model_name)

    mode_label = "Regular" if mode == "regular" else "⚡ MAXIMUM OVERDRIVE ⚡"

    if context_content:
        prompt = f"""{instructions}

---
# About Jack (shared context)
{context_content}
---

Current mode: {mode_label}"""
    else:
        # No context mode — just instructions + mode
        prompt = f"""{instructions}

Current mode: {mode_label}"""

    if protocol_role_prompt:
        prompt += f"\n\n---\n{protocol_role_prompt}"

    return prompt


def get_current_context(session) -> str:
    """Load the most recent context document from DB (legacy monolithic)."""
    result = session.exec(
        select(ContextDoc).order_by(ContextDoc.id.desc())  # type: ignore
    ).first()

    return result.content if result else ""


def update_context(session, content: str, source: str = "manual") -> None:
    """Save a new version of the context document."""
    doc = ContextDoc(content=content, source=source)
    session.add(doc)
    session.commit()
