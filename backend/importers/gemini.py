"""
Gemini (Google Takeout) export parser.

Input: ZIP from takeout.google.com → "My Activity" → "Gemini Apps" selected
  Extract ZIP → Takeout/My Activity/Gemini Apps/MyActivity.html

Format:
  The HTML contains a series of outer-cell divs, each representing one interaction.
  Each outer-cell has a content-cell div structured as:
    "Prompted [user message text]"
    <br>timestamp<br>
    <p>Response paragraph 1</p>
    <p>Response paragraph 2</p>
    ...

  Some entries are just "Visited Gemini Apps" with no prompt — skip those.
"""
import re
import os
import html as html_lib


def parse_gemini_export(export_dir: str) -> list[dict]:
    """
    Parse extracted Gemini Takeout directory into conversations.

    Args:
        export_dir: Path to extracted Takeout directory (or Gemini Apps dir)

    Returns: list of {title, created_at, messages[{role, content}]}
    """
    # Find MyActivity.html — could be at various paths
    candidates = [
        os.path.join(export_dir, "My Activity", "Gemini Apps", "MyActivity.html"),
        os.path.join(export_dir, "MyActivity.html"),
        export_dir,  # If they passed the file directly
    ]

    html_path = None
    for path in candidates:
        if os.path.isfile(path):
            html_path = path
            break

    if not html_path:
        return []

    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    return _parse_html_activities(html_content)


def _parse_html_activities(html_content: str) -> list[dict]:
    """Parse the Gemini MyActivity.html file into conversations."""
    conversations = []

    # Find each outer-cell block by splitting on outer-cell div starts
    starts = [m.start() for m in re.finditer(r'<div class="outer-cell', html_content)]
    if not starts:
        return []

    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(html_content)
        block = html_content[start:end]

        # Extract the content-cell text
        content_match = re.search(
            r'<div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1">(.*?)</div>',
            block,
            re.DOTALL,
        )
        if not content_match:
            continue

        cell_html = content_match.group(1)

        # Skip non-prompt entries (e.g., "Visited Gemini Apps")
        if not cell_html.strip().startswith("Prompted"):
            continue

        # Extract user prompt: everything after "Prompted " up to the first <br> with a date
        # The timestamp pattern: "Mon DD, YYYY, HH:MM:SS AM/PM TZ"
        timestamp_pattern = r'[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4},\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M\s+\w+'

        # Split on timestamp — text before is prompt, text after is response
        # First, strip HTML tags for the prompt part
        # The structure is: "Prompted [text]<br>...<br>timestamp<br><p>response</p>..."

        # Find the timestamp
        ts_match = re.search(timestamp_pattern, cell_html)
        if not ts_match:
            continue

        timestamp_str = ts_match.group(0)
        ts_pos = ts_match.start()

        # Everything before the timestamp is the prompt area
        prompt_html = cell_html[:ts_pos]
        # Everything after is the response
        response_html = cell_html[ts_match.end():]

        # Clean prompt: remove "Prompted " prefix, strip tags, unescape
        prompt_text = re.sub(r'<[^>]+>', ' ', prompt_html).strip()
        if prompt_text.startswith("Prompted"):
            prompt_text = prompt_text[len("Prompted"):].strip()
        # Remove attachment references
        prompt_text = re.sub(r'Attached \d+ files?\..*$', '', prompt_text, flags=re.DOTALL).strip()
        prompt_text = html_lib.unescape(prompt_text).strip()

        if not prompt_text:
            continue

        # Clean response: strip tags, unescape
        response_text = re.sub(r'<[^>]+>', '\n', response_html)
        response_text = html_lib.unescape(response_text).strip()
        # Collapse multiple newlines
        response_text = re.sub(r'\n{3,}', '\n\n', response_text)

        if not response_text:
            continue

        # Each entry is a single-turn "conversation"
        # Use first ~50 chars of prompt as title
        title = prompt_text[:60].strip()
        if len(prompt_text) > 60:
            title += "..."

        conversations.append({
            "title": title,
            "created_at": timestamp_str,
            "messages": [
                {"role": "user", "content": prompt_text},
                {"role": "assistant", "content": response_text},
            ],
        })

    return conversations
