"""
Context engine — distillation pipeline for raw chat exports.

Pipeline:
1. Raw exports (ChatGPT/Gemini/Claude JSON) → Parser
2. Parsed conversations → Chunker (~4K token chunks)
3. Per-chunk summarizer (Claude Opus extracts durable facts)
4. Merger / Deduplicator (newer info wins)
5. Final distiller → single structured markdown document

Output supplements the manually-written context doc, does NOT replace it.
One-time cost: ~$2-5 for ~100 conversations.
"""


DISTILL_SYSTEM_PROMPT = """You are distilling a user's AI chat history into a structured context document.

Given conversation summaries, produce a single markdown document capturing everything another AI needs to know for productive, personalized conversation with this person.

Organize by category:
- Identity & situation
- Active projects & priorities
- Preferences & communication style
- Key relationships & contacts
- Technical environment
- Health & personal
- Open action items

Be specific — include names, dates, project names, technical details.
Prefer recent information over old. Flag contradictions.
Do NOT include conversation-level details — extract DURABLE facts only."""

CHUNK_SUMMARY_PROMPT = """Extract durable facts about the user from these conversations.
Focus on: preferences, projects, decisions, relationships, technical setup, health, goals.
Ignore: transient questions, greetings, debugging sessions unless they reveal preferences.
Return a bullet list of facts. Be specific."""


async def distill_conversations(conversations: list[dict], existing_context: str) -> str:
    """
    Distill raw parsed conversations into structured context.

    Args:
        conversations: Parsed conversations from any importer
        existing_context: Current context doc (to merge with)

    Returns:
        Updated context markdown string
    """
    # TODO Step 5: implement chunking → summarization → merge → distill
    # Rough outline:
    #
    # 1. Flatten all conversations into text chunks of ~4K tokens
    # chunks = chunk_conversations(conversations, max_tokens=4000)
    #
    # 2. Summarize each chunk via Claude Opus
    # summaries = []
    # for chunk in chunks:
    #     summary = await call_opus(CHUNK_SUMMARY_PROMPT, chunk)
    #     summaries.append(summary)
    #
    # 3. Merge summaries + existing context
    # merged = "\n\n".join(summaries)
    # merged += "\n\n# Existing context (manually written):\n" + existing_context
    #
    # 4. Final distillation pass
    # result = await call_opus(DISTILL_SYSTEM_PROMPT, merged)
    # return result
    pass


def chunk_conversations(conversations: list[dict], max_tokens: int = 4000) -> list[str]:
    """Split conversations into text chunks under max_tokens (~4 chars/token)."""
    chunks = []
    current = ""
    max_chars = max_tokens * 4

    for conv in conversations:
        title = conv.get("title", "Untitled")
        text = f"\n## {title}\n"
        for msg in conv.get("messages", []):
            role = msg.get("role", "?")
            content = msg.get("content", "")
            text += f"{role}: {content}\n"

        if len(current) + len(text) > max_chars:
            if current:
                chunks.append(current)
            current = text
        else:
            current += text

    if current:
        chunks.append(current)

    return chunks
