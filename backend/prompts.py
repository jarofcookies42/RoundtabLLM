"""Prompts for background tasks (Compaction and AutoDream) and LLM orchestration."""

COMPACTION_SYSTEM_PROMPT = "You are a conversation compactor. Output only the summary."

DREAM_SYSTEM_PROMPT = "You are a memory consolidation agent. Output only valid JSON."

COMPACTION_PROMPT = """You are compacting a multi-AI roundtable conversation to save context space. Below is the older portion of the conversation that needs to be summarized.

Participants: Jack (human user), Claude, GPT-5.4, Gemini 3.1 Pro, Grok 4.20

Transcript to summarize:
{transcript}

Create a concise summary that preserves:
- Key decisions and conclusions reached
- Important disagreements between models (who said what)
- Action items or commitments Jack made
- Any facts, data, or references that were shared
- The overall arc of the discussion

Do NOT preserve:
- Greetings, pleasantries, meta-commentary about the roundtable itself
- Redundant agreement ("I agree with Claude" when the agreement adds nothing)
- Test messages or debugging

Format as a compact narrative paragraph, not bullet points. Keep it under 500 tokens. Start with "Earlier in this conversation:" so models know this is a summary, not a real message."""

DREAM_PROMPT = """You are a memory consolidation agent performing a "dream pass" — reviewing recent conversation transcripts to update a user's persistent memory files.

## Current memory state
Total size: {total_chars} chars, {total_lines} lines across {num_topics} topic files.

{topic_sections}

## Recent conversation transcripts
{transcripts}

## Your job

Phase 1 — GATHER: Identify NEW durable facts from the transcripts. Look for: preferences, decisions, project updates, relationship changes, completed tasks, new skills, new contacts, schedule changes. Do NOT extract: greetings, transient debugging, small talk, questions fully resolved in-conversation.

Phase 2 — CONSOLIDATE: Identify information in existing topic files that should be updated based on the transcripts. Merge related observations rather than keeping both. Examples:
- "user might prefer X" + transcript confirms X → replace old entry with confirmed fact
- "project status: planning" + transcript shows it shipped → update to shipped
- Convert vague insights into concrete facts where transcripts support it

Phase 3 — PRUNE: Identify stale, duplicated, or contradicted entries across topic files that should be removed or merged.

## Output format

Output a JSON object with this exact structure:
{{
  "additions": [
    {{"topic": "projects", "content": "text to append", "reason": "why"}},
  ],
  "updates": [
    {{"topic": "thesis", "old_content": "exact substring to replace", "new_content": "replacement text", "reason": "why"}}
  ],
  "deletions": [
    {{"topic": "projects", "content": "exact substring to remove", "reason": "why"}}
  ],
  "summary": "2-3 sentence summary of what changed and why",
  "no_changes_needed": false
}}

## Constraints

- HARD CAP: Total memory across all topic files must stay under {cap_chars} chars / {cap_lines} lines. Current: {total_chars} chars, {total_lines} lines. If adding new content would exceed this, you MUST also propose deletions or merges to stay under the cap.
- Never reduce any single topic file by more than 50% in one dream pass. If a topic needs heavy pruning, flag it in the summary and spread the work across multiple passes.
- Merge related observations rather than keeping duplicates.
- Convert vague insights into concrete facts where the transcripts support it.
- Memory is a hint system, not a source of truth. Do not consolidate speculative or uncertain information as if it were confirmed.
- Be conservative. Only propose changes you're confident about. When in doubt, leave it alone. The user will review every proposed change before it's applied.
- Use exact substrings for old_content in updates and content in deletions — the apply step does literal string matching.
- Output ONLY the JSON object. No markdown fences, no explanation outside the JSON."""
