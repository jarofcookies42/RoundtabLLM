"""
Claude (Anthropic) export parser.

Input: conversations.json from Claude data export
  (Settings → Account → Export Data)

Structure:
[
  {
    "uuid": "...",
    "name": "conversation title",
    "created_at": "2026-01-28T...",
    "updated_at": "2026-03-25T...",
    "chat_messages": [
      {
        "uuid": "...",
        "sender": "human" | "assistant",
        "text": "message content",
        "content": [...],
        "created_at": "...",
        "attachments": [],
        "files": []
      }
    ]
  }
]

Notes:
- sender is "human" or "assistant" (NOT "user")
- Both "text" and "content" fields exist; prefer "text" as it's the plain string
- Attachments are referenced but content is not inline
- Some conversations may have empty chat_messages (projects data is separate)
"""
import json


def parse_claude_export(raw_json: str) -> list[dict]:
    """
    Parse Claude conversations.json into standard format.

    Returns: list of {title, created_at, messages[{role, content}]}
    """
    data = json.loads(raw_json)
    conversations = []

    for conv in data:
        msgs = conv.get("chat_messages", [])
        if not msgs:
            continue

        parsed_messages = []
        for msg in msgs:
            sender = msg.get("sender", "")
            # Map Claude's "human" to our "user"
            role = "user" if sender == "human" else "assistant"

            # Prefer "text" field; fall back to extracting from "content" array
            text = msg.get("text", "")
            if not text and msg.get("content"):
                # content is a list of blocks; extract text from text blocks
                parts = []
                for block in msg["content"]:
                    if isinstance(block, str):
                        parts.append(block)
                    elif isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                text = "\n".join(parts)

            if not text:
                continue

            parsed_messages.append({"role": role, "content": text})

        if not parsed_messages:
            continue

        conversations.append({
            "title": conv.get("name", "Untitled"),
            "created_at": conv.get("created_at", ""),
            "messages": parsed_messages,
        })

    return conversations
