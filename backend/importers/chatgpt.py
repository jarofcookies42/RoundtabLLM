"""
ChatGPT export parser.

Input: conversations.json from ChatGPT data export
  (Settings → Data Controls → Export data → ZIP → conversations.json)

The JSON is a list of conversation objects. Each conversation has a 'mapping' dict
which is a TREE of messages (not a flat list). Walk parent→children to reconstruct
linear conversation order.

Structure:
[
  {
    "title": "...",
    "create_time": 1710000000.0,
    "mapping": {
      "msg-id-1": {
        "message": {
          "author": {"role": "user" | "assistant" | "system" | "tool"},
          "content": {"parts": ["text content here"]},
          "create_time": 1710000000.0
        },
        "parent": "parent-msg-id" | null,
        "children": ["child-msg-id", ...]
      }
    }
  }
]

Notes:
- Some messages have content: null (system turns, empty) — skip them
- parts[] can contain text, image refs, or tool outputs — extract text only
- Walk tree from root (parent=null) following children to get linear order
"""
import json
from datetime import datetime


def parse_chatgpt_export(raw_json: str) -> list[dict]:
    """
    Parse ChatGPT conversations.json into a flat list of conversations.

    Returns:
    [
        {
            "title": "...",
            "created_at": "2026-01-15T...",
            "messages": [
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": "..."},
            ]
        }
    ]
    """
    data = json.loads(raw_json)
    conversations = []

    for conv in data:
        mapping = conv.get("mapping", {})
        if not mapping:
            continue

        messages = _walk_message_tree(mapping)
        if not messages:
            continue

        created_at = ""
        if conv.get("create_time"):
            try:
                created_at = datetime.fromtimestamp(conv["create_time"]).isoformat()
            except (ValueError, OSError):
                pass

        conversations.append({
            "title": conv.get("title", "Untitled"),
            "created_at": created_at,
            "messages": messages,
        })

    return conversations


def _walk_message_tree(mapping: dict) -> list[dict]:
    """Walk the mapping tree from root to leaves, returning messages in order."""
    # Find root node: one whose parent is None or whose parent isn't in the mapping
    root_id = None
    for msg_id, node in mapping.items():
        parent = node.get("parent")
        if parent is None or parent not in mapping:
            root_id = msg_id
            break

    if root_id is None:
        return []

    # Walk the tree following first child at each level
    messages = []
    current_id = root_id

    while current_id:
        node = mapping.get(current_id)
        if not node:
            break

        msg = node.get("message")
        if msg:
            author = msg.get("author", {})
            role = author.get("role", "")
            content_obj = msg.get("content", {})

            # Only include user and assistant messages
            if role in ("user", "assistant") and content_obj:
                parts = content_obj.get("parts", [])
                # Extract text parts only (skip image/tool refs)
                text_parts = []
                for part in parts:
                    if isinstance(part, str) and part.strip():
                        text_parts.append(part)
                    elif isinstance(part, dict) and part.get("text"):
                        text_parts.append(part["text"])

                text = "\n".join(text_parts).strip()
                if text:
                    messages.append({"role": role, "content": text})

        # Follow first child to continue the linear path
        children = node.get("children", [])
        current_id = children[0] if children else None

    return messages
