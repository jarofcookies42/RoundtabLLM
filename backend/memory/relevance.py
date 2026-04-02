"""
Keyword-based relevance detection for memory topics.

Matches user messages against the memory index to determine which topic files
to load. Simple and fast — no embeddings, no LLM calls.
"""
import re

STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "must", "ought",
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "it",
    "they", "them", "their", "this", "that", "these", "those", "what",
    "which", "who", "whom", "how", "when", "where", "why", "if", "then",
    "and", "or", "but", "not", "no", "so", "too", "very", "just",
    "about", "for", "with", "from", "into", "of", "on", "in", "at",
    "to", "by", "up", "out", "off", "over", "under", "again", "also",
    "all", "any", "some", "more", "most", "other", "each", "every",
    "than", "like", "get", "got", "make", "made", "take", "see", "know",
    "think", "want", "tell", "help", "let", "try", "go", "come", "say",
    "said", "new", "old", "good", "bad", "much", "many", "well", "here",
    "there", "now", "still", "even", "back", "way", "thing", "things",
})

DEFAULT_TOPICS = ["identity", "work_style"]
MAX_TOPICS = 3
MIN_TOPICS = 1


def _tokenize(text: str) -> set[str]:
    """Extract significant lowercase words from text."""
    words = re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 2}


def _parse_index(index_content: str) -> dict[str, set[str]]:
    """Parse memory_index.md into {topic_key: set_of_keywords}."""
    topics = {}
    for line in index_content.strip().splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, description = line.split(":", 1)
        key = key.strip()
        # Remove the "See xyz.md" suffix
        description = re.sub(r"\s*See\s+\w+\.md\s*$", "", description, flags=re.IGNORECASE)
        topics[key] = _tokenize(description)
    return topics


def detect_relevant_topics(
    message: str,
    recent_messages: list[str],
    index_content: str,
) -> list[str]:
    """
    Score topics by keyword overlap with the user's message and recent history.

    Returns 1-3 topic keys sorted by relevance score (highest first).
    Falls back to identity + work_style if nothing matches.
    """
    topics = _parse_index(index_content)
    if not topics:
        return list(DEFAULT_TOPICS)

    # Combine current message + recent messages into one token set
    all_text = message
    for msg in recent_messages[-3:]:
        all_text += " " + msg
    query_tokens = _tokenize(all_text)

    if not query_tokens:
        return list(DEFAULT_TOPICS)

    # Score each topic by keyword overlap
    scores: list[tuple[str, int]] = []
    for key, keywords in topics.items():
        score = len(query_tokens & keywords)
        if score > 0:
            scores.append((key, score))

    if not scores:
        return list(DEFAULT_TOPICS)

    # Sort by score descending, take top MAX_TOPICS
    scores.sort(key=lambda x: x[1], reverse=True)
    result = [key for key, _ in scores[:MAX_TOPICS]]

    return result
