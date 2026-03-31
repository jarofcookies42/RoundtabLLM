"""
Context engine — assembles system prompts with shared memory context.

The system prompt structure for every model:
1. Group chat behavior instructions
2. Shared context document (Jack's background, projects, preferences)
3. Current mode indicator
"""


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
        context_content: The shared context document (markdown)
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

    prompt = f"""{instructions}

---
# About Jack (shared context)
{context_content}
---

Current mode: {mode_label}"""

    if protocol_role_prompt:
        prompt += f"\n\n---\n{protocol_role_prompt}"

    return prompt


def get_current_context(session) -> str:
    """Load the most recent context document from DB."""
    from ..models import ContextDoc
    from sqlmodel import select

    result = session.exec(
        select(ContextDoc).order_by(ContextDoc.id.desc())  # type: ignore
    ).first()

    return result.content if result else ""


def update_context(session, content: str, source: str = "manual") -> None:
    """Save a new version of the context document."""
    from ..models import ContextDoc
    
    doc = ContextDoc(content=content, source=source)
    session.add(doc)
    session.commit()
