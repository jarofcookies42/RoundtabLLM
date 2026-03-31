# RoundtabLLM — Technical Documentation

## What This Is

A self-hosted multi-LLM deliberation engine. Jack sends a message, and 2-4 AI models respond in configurable order using one of three protocols. Every model sees the full conversation history including other models' responses. A shared "memory" context document is injected into every model's system prompt so they all know Jack's background, projects, and preferences.

## Architecture

- **Backend:** FastAPI (Python), SQLite via SQLModel, SSE streaming
- **Frontend:** React + Vite, dark theme, JetBrains Mono + Sora fonts
- **Deploy target:** Railway

## Implementation Status

### Completed
- **Phase 1:** Thinking capture, model fixes, streaming reliability
- **Phase 2:** Protocol switcher (Roundtable, Blind, Debate)
- **Phase 3A:** Debate role assignment UI with constraint enforcement
- **Phase 3B:** Session-to-artifact markdown export
- **Phase 3C:** Artifact uploader (file attach to chat input)
- **Core:** All four model clients, mode/anchor switching, context system, import pipeline, auth, deploy config

### Future Work (TODO)
- **Forced Dissent mode** — inject "you MUST disagree" into system prompts. Toggle in UI alongside protocol selector.
- **Divergence Heatmap** — semantic similarity tracking between model responses per round with color-coded UI grid.
- **Chain-of-Thought Leakage Monitor** — detect when thinking_content themes bleed into visible responses. Flag with warning badge.
- **Per-model thinking/reasoning sliders** — let user override thinking_level, reasoning_effort, and thinking.budget_tokens per model from the UI.

## Two Modes

Toggled by a single switch in the UI header:

### Regular Mode (~$0.02/round)
| Model | Config |
|-------|--------|
| Claude Sonnet 4.6 | `thinking: {type: "enabled", budget_tokens: 4096}`, `max_tokens: 8192` |
| GPT-5.4 | `reasoning_effort: "none"`, `verbosity: "medium"`, `max_tokens: 1024` |
| Gemini 3.1 Pro | `temperature: 1.0`, `thinking_level: "low"`, `top_p: 0.95`, `max_tokens: 2048` |
| Grok (`grok-4-1-fast-non-reasoning`) | `temperature: 0.7`, `max_tokens: 1024` |

### Maximum Overdrive (~$0.15-0.40/round)
| Model | Config |
|-------|--------|
| Claude Opus 4.6 | `thinking: {type: "adaptive"}`, `max_tokens: 32000`, `effort: "max"` |
| GPT-5.4 | `reasoning_effort: "high"`, `verbosity: "high"`, `max_tokens: 2048` |
| Gemini 3.1 Pro | `temperature: 1.0`, `thinking_level: "high"` (Deep Think Mini), `top_p: 0.95`, `max_tokens: 4096` |
| Grok (`grok-4-1-fast-reasoning`) | `temperature: 0.9`, `max_tokens: 2048` |

## Two Anchor Modes

Independent toggle from Regular/Overdrive. Controls which model responds LAST (the "anchor"):

- **Knowledge anchor** → Claude goes last. Order: Grok → GPT → Gemini → Claude. Best for professional knowledge work, coding, nuanced analysis.
- **Abstract anchor** → Gemini goes last. Order: Grok → GPT → Claude → Gemini. Best for abstract reasoning, novel logic, scientific synthesis.

The anchor model gets the richest context because it sees all other models' responses before generating its own.

## Three Protocols

### Roundtable (default)
Sequential round-robin. Each model sees all previous responses. The anchor goes last and sees everything. Implemented in `run_round()`.

### Blind → Synthesis
All models answer independently in parallel (no visibility of each other). After all finish, the anchor gets all responses and synthesizes. Implemented in `run_blind()`. Uses `asyncio.Queue` for interleaved parallel SSE streaming.

### Debate
Three-phase structured deliberation. Implemented in `run_debate()`:
1. **Proposal phase** — Two proposers answer in parallel (blind to each other).
2. **Critic phase** — A critic evaluates both proposals. Proposals are **anonymized** ("Proposal 1", "Proposal 2") so the critic can't be biased by model identity.
3. **Synthesis phase** — The arbiter synthesizes with full attribution restored (knows which model wrote which proposal).

**Role assignment:** Users can assign roles (Proposer/Critic/Synthesizer) to any model via clickable badges on model chips. Constraints are enforced: 2 proposers, 1 critic, 1 synthesizer (for 4 models). Same-model proposer+critic is intentionally supported — anonymization ensures no self-knowledge. The `debate_roles` dict is passed from frontend to backend. If not provided, roles fall back to position-based assignment.

Protocol-specific system prompts are defined in `PROTOCOL_PROMPTS` dict in `backend/context/__init__.py`.

## Thinking/Reasoning Capture

### Claude (thinking_content stored)
Claude's `thinking` blocks are captured during streaming via the `ThinkingStream` wrapper class in `backend/llm/claude.py`. The wrapper intercepts `content_block_start` and `content_block_delta` events, accumulating thinking text separately from visible response text. After streaming completes, `thinking_content` is saved to the Message record. Only visible `text` blocks are streamed to the frontend.

### Gemini (wired but unsupported)
The Gemini client is wired to pass `include_thoughts=True` in generation config, but the Google GenAI SDK doesn't yet support thought extraction for Gemini 3.1 Pro. `thinking_content` is stored as `None`.

### GPT-5.4 and Grok (hidden by API)
Both models' reasoning tokens are hidden by their respective APIs. You pay for reasoning tokens but they don't appear in the response. `thinking_content` is stored as `None`.

## CRITICAL: Temperature Rules

These cause API errors or degraded output if violated:

- **Claude:** When `thinking` is enabled, temperature and top_k CANNOT be set at all. Do not pass temperature when using thinking mode.
- **GPT-5.4:** Temperature is LOCKED at 1. Passing any other value returns a 400 error. The only control knob is `reasoning_effort`.
- **Gemini 3.1 Pro:** Temperature MUST stay at 1.0. Values below 1.0 cause response looping and performance degradation. Google explicitly warns against changing it.
- **Grok:** Only model where temperature is a free parameter (0.0–1.0).

## API Details

### Claude (Anthropic SDK) — `backend/llm/claude.py`
```python
# Regular
client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=8192,
    thinking={"type": "enabled", "budget_tokens": 4096},
    system=system_prompt,
    messages=formatted_messages,
)

# Overdrive
client.messages.create(
    model="claude-opus-4-6",
    max_tokens=32000,
    thinking={"type": "adaptive"},
    system=system_prompt,
    messages=formatted_messages,
)
```
Response content blocks include both `thinking` and `text` types. The `ThinkingStream` wrapper separates them during streaming.

Claude requires alternating user/assistant messages. All non-Claude model messages become "user" role with `[ModelName]: ` prefix. Consecutive same-role messages are merged.

### GPT-5.4 (OpenAI SDK) — `backend/llm/openai_client.py`
```python
# Regular
client.chat.completions.create(
    model="gpt-5.4",
    messages=formatted_messages,
    max_tokens=1024,
    # temperature not passed — only default (1) is supported
)

# Overdrive
client.chat.completions.create(
    model="gpt-5.4",
    messages=formatted_messages,
    max_tokens=2048,
    reasoning_effort="high",
)
```

### Gemini 3.1 Pro (Google GenAI SDK) — `backend/llm/gemini.py`
```python
model = genai.GenerativeModel("gemini-3.1-pro-preview")
response = model.generate_content(
    contents=formatted_contents,
    generation_config=genai.GenerationConfig(
        temperature=1.0,
        top_p=0.95,
        max_output_tokens=2048,  # 4096 in Overdrive
    ),
)
```
Gemini uses "user"/"model" roles (not "assistant"). System instructions are separate via `system_instruction` parameter.

### Grok (OpenAI-compatible via xAI) — `backend/llm/grok.py`
```python
client = openai.OpenAI(
    api_key=grok_key,
    base_url="https://api.x.ai/v1",
)
client.chat.completions.create(
    model="grok-4-1-fast-non-reasoning",  # grok-4-1-fast-reasoning in Overdrive
    messages=formatted_messages,
    temperature=0.7,  # 0.9 in Overdrive
    max_tokens=1024,  # 2048 in Overdrive
)
```

## Message History Formatting

Each model needs the conversation history formatted differently:

1. **Claude**: Alternating user/assistant. Own previous messages = "assistant". Everything else = "user" with `[Name]: content` prefix. Merge consecutive same-role messages with newlines.
2. **GPT-5.4 / Grok**: System message first, then messages. Own previous = "assistant". Everything else = "user" with `[Name]: content` prefix.
3. **Gemini**: System instruction separate. Own previous = "model" role. Everything else = "user" with `[Name]: content` prefix.

## Shared Context (System Prompt Structure)

Every model gets:
```
[Model-specific group chat instructions — varies by protocol]

[Shared context document — loaded from DB, editable in UI]

[Mode indicator — "Regular" or "MAXIMUM OVERDRIVE"]

[Protocol role prompt — if applicable (critic, arbiter, synthesis)]
```

The shared context document is seeded from `context/jack_context.md` on first run. It's editable in the UI's "Memory / Context" tab.

## Session Export

`GET /conversations/{id}/export` returns a markdown file with:
- Metadata table (date, mode, anchor, protocol, models)
- All messages with protocol role tags (e.g. `proposal`, `critic`, `synthesis`)
- Collapsed `<details>` sections for thinking_content where available
- Disagreement analysis placeholder (future feature)

Filename format: `roundtabllm-{id}-{date}.md`. Frontend triggers browser download via blob URL.

## Artifact Uploader

Files can be attached to chat messages via drag-and-drop or the 📎 button in the input bar.

- **Supported types:** `.md`, `.txt`, `.py`, `.json`, `.js`, `.ts`, `.jsx`, `.tsx`, `.css`, `.html`, `.yaml`, `.yml`, `.toml`, `.csv`, `.pdf`
- **Size limits:** 100KB for text files, 1MB for PDFs
- File contents are prepended to the message in a fenced code block: `[Attached: filename]\n```\n...content...\n````
- A file chip shows the filename and size above the input bar with a dismiss button.

## Routes

| Method | Path | Description |
|--------|------|-------------|
| POST | `/chat` | Send a message, returns conversation_id |
| GET | `/chat/stream/{conv_id}` | SSE stream of model responses |
| GET | `/conversations` | List conversations |
| GET | `/conversations/{id}` | Get full conversation with messages |
| GET | `/conversations/{id}/export` | Download conversation as markdown |
| GET | `/context` | Get current shared context document |
| POST | `/context` | Update shared context document |
| POST | `/import/{platform}` | Upload a chat export (chatgpt, gemini, claude) |

Auth: Bearer token via `Authorization` header or `?token=` query param.

## SSE Event Format

All three protocols emit the same event types:
```
data: {"type": "model_start", "model": "claude", "name": "Claude Sonnet 4.6", "protocol_role": "proposal"}
data: {"type": "token", "model": "claude", "delta": "Hello"}
data: {"type": "model_done", "model": "claude", "content": "full response", "protocol_role": "proposal"}
data: {"type": "model_error", "model": "claude", "error": "timeout"}
data: {"type": "round_done"}
```

## Project Structure

```
roundtabllm/
├── CLAUDE.md               ← technical documentation (you are here)
├── README.md               ← project README for GitHub
├── Procfile                ← Railway process definition
├── railway.toml            ← Railway deploy config
├── .env.example            ← template for environment variables
├── .gitignore
├── context/
│   └── jack_context.md     ← seed context document
├── backend/
│   ├── __init__.py
│   ├── main.py             ← FastAPI app, all routes
│   ├── config.py           ← env vars, model configs, mode definitions
│   ├── models.py           ← SQLModel schemas (Conversation, Message, ContextDoc, RawImport)
│   ├── database.py         ← SQLite setup + migrations
│   ├── requirements.txt
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── router.py       ← protocol orchestrator (roundtable, blind, debate) + SSE streaming
│   │   ├── claude.py       ← Anthropic client + ThinkingStream wrapper
│   │   ├── openai_client.py ← GPT-5.4 client
│   │   ├── gemini.py       ← Google GenAI client
│   │   └── grok.py         ← Grok client (OpenAI-compat via xAI)
│   ├── context/
│   │   └── __init__.py     ← context assembly, system prompts, PROTOCOL_PROMPTS
│   └── importers/
│       ├── __init__.py
│       ├── chatgpt.py      ← parse ChatGPT export JSON
│       ├── gemini.py       ← parse Google Takeout Gemini data
│       └── claude_export.py ← parse Claude export JSON
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── main.jsx
│       ├── App.jsx          ← main app shell, state management, tab routing
│       ├── api.js           ← fetch wrappers for backend + export download
│       ├── hooks/
│       │   └── useSSE.js    ← Server-Sent Events streaming hook
│       └── components/
│           ├── ChatView.jsx      ← message list + input + file attach (drag-and-drop)
│           ├── MessageBubble.jsx ← per-model styled message + protocol role badges
│           ├── ModelChips.jsx    ← model toggles + debate role assignment (P/C/S badges)
│           ├── ModeToggle.jsx    ← Regular / Maximum Overdrive switch
│           ├── AnchorToggle.jsx  ← Knowledge / Abstract anchor switch
│           ├── ProtocolToggle.jsx ← Roundtable / Blind / Debate cycle toggle
│           └── ContextEditor.jsx ← shared memory document editor
└── backend/static/          ← Vite build output (gitignored)
```

## Environment Variables

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_AI_API_KEY=AIza...
GROK_API_KEY=xai-...
AUTH_TOKEN=some-random-string-for-simple-auth
```

## Key Decisions

- SQLite not Postgres (personal tool, zero config)
- SSE not WebSockets (simpler, one-way streaming is sufficient)
- Sequential not parallel model calls in Roundtable (each model builds on previous — that's the whole point)
- Parallel calls in Blind and Debate proposal phases (independence is the point)
- Sonnet default, Opus only in Overdrive (cost savings for similar quality)
- Temperature is effectively fixed at 1.0 for Claude/GPT/Gemini — thinking/reasoning params are the real control knobs
- Debate anonymization ensures fair critique regardless of model identity
- Protocol role assignment is user-controllable but has sensible position-based defaults

## Style Notes

- Dark UI with amber/gold (#D97706) as primary accent
- Model colors: Claude = amber (#D97706), GPT = green (#10B981), Gemini = indigo (#6366F1), Grok = pink (#EC4899)
- Monospace font for chat (JetBrains Mono)
- Display font for headers (Sora)
- Each message has a colored left border matching its model
- Anchor model messages get a subtle "anchor" badge
- Debate messages get protocol role badges (proposal/critic/synthesis)
