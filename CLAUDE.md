# RoundtabLLM — Technical Documentation

## What This Is

A self-hosted multi-LLM deliberation engine with a scalable memory architecture. Jack sends a message, and 2-4 AI models respond in configurable order using one of three protocols. A memory-as-hint system loads only relevant context per round via keyword matching against topic files, keeping token costs bounded. AutoDream consolidation scans recent conversations and proposes memory updates for user review. Every message and memory entry carries provenance metadata (source + trust tier). Long conversations auto-compact by summarizing older messages while keeping recent ones verbatim.

## Architecture

- **Backend:** FastAPI (Python), SQLite via SQLModel, SSE streaming
- **Frontend:** React + Vite, dark theme, JetBrains Mono + Sora fonts
- **Deploy target:** Railway (live at production URL, persistent volume for SQLite)

## Implementation Status

### Completed
- **Phase 1:** Thinking capture, model fixes, streaming reliability
- **Phase 2:** Protocol switcher (Roundtable, Blind, Debate)
- **Phase 3A:** Debate role assignment UI with constraint enforcement
- **Phase 3B:** Session-to-artifact markdown export
- **Phase 3C:** Artifact uploader (file attach to chat input)
- **Phase 4A:** Memory-as-hint refactor — topic files + relevance detection + context mode toggle (Full/Select/None)
- **Phase 4B:** AutoDream memory consolidation — Claude-powered dream passes with user-reviewed diffs
- **Phase 4C:** Context provenance tagging — source + trust_tier on every message and memory file
- **Phase 4D:** Compaction pipeline — auto-summarize old messages when context exceeds 30K tokens
- **Core:** All four model clients, mode/anchor switching, import pipeline, auth, deploy config, static file serving, Railway persistent volume

### Future Work
- **Phase 5 — Imports:** Full import pipeline for ChatGPT/Gemini/Claude exports with conversation replay
- **Forced Dissent mode** — inject "you MUST disagree" into system prompts
- **Divergence Heatmap** — semantic similarity tracking between model responses per round
- **Chain-of-Thought Leakage Monitor** — detect when thinking_content themes bleed into visible responses
- **Per-model thinking/reasoning sliders** — let user override thinking_level, reasoning_effort, and thinking.budget_tokens per model from the UI

## Memory Architecture (Phase 4)

### Memory-as-Hint (4A)
Replaced monolithic context injection with a pointer index + on-demand topic files:
- **memory_index.md** — one-line-per-topic with trigger keywords (~800 chars, always loaded)
- **7 topic files** — identity, thesis, projects, health, family, tech, work_style (loaded on demand, max 3 per round)
- **Relevance detection** (`backend/memory/relevance.py`) — keyword matching against user message + last 2-3 messages. Falls back to identity + work_style for generic messages.
- **Context modes** — Full (auto-detect), Select (manual checkboxes), None (blank slate). Stored per conversation.
- **MemoryFile model** — key, content, file_type ("index"/"topic"), source, last_modified_by, derived_from, updated_at

### AutoDream (4B)
Memory consolidation via dream passes (`backend/memory/autodream.py`):
- Scans conversations since last successful dream (or last 5 if no prior dream)
- Calls Claude Sonnet with a structured prompt to extract additions, updates, and deletions
- Proposes a diff for user review — never auto-applies
- Consolidation lock prevents concurrent dream passes
- 25KB / 200-line hard cap on total memory size
- **DreamLog model** — status, proposed_changes, applied_changes, conversations_processed, summary, token_cost

### Provenance (4C)
Every message and memory entry carries provenance metadata:
- **Message.source** — "user", "claude", "gpt", "gemini", "grok", "system", "autodream"
- **Message.trust_tier** — "direct" (user typed), "model" (AI response), "derived" (synthesis/compaction), "imported", "system" (errors)
- **MemoryFile.source** — "seed", "manual", "autodream", "import"
- **MemoryFile.last_modified_by** — "user", "autodream", "import_distiller"
- **MemoryFile.derived_from** — JSON linking to source dream/import
- Provenance badges only appear in chat UI for non-default tiers (derived, imported, system)
- Exports include provenance on non-default tier messages

### Compaction (4D)
Auto-summarizes old messages when context exceeds 30K tokens (`backend/memory/compaction.py`):
- Splits messages into old (compacted) and recent (kept verbatim, default last 6)
- Calls Claude Sonnet to generate a summary starting with "Earlier in this conversation:"
- Compacted messages stay in DB (flagged `compacted=True`) for export and AutoDream but are excluded from model context
- Models see: [compaction summary] + [recent verbatim messages]
- Auto-triggers at start of each round when context pressure is high
- Manual compaction via `POST /conversations/{id}/compact`
- Context pressure indicator in chat UI (green/amber/red progress bar)

## Two Modes

Toggled by a single switch in the UI header:

### Regular Mode (~$0.02/round)
| Model | Config |
|-------|--------|
| Claude Sonnet 4.6 | `thinking: {type: "enabled", budget_tokens: 4096}`, `max_tokens: 8192` |
| GPT-5.4 | `reasoning_effort: "none"`, `verbosity: "medium"`, `max_tokens: 1024` |
| Gemini 3.1 Pro | `temperature: 1.0`, `thinking_level: "low"`, `top_p: 0.95`, `max_tokens: 2048` |
| Grok 4.20 (`grok-4.20-non-reasoning`) | `temperature: 0.7`, `max_tokens: 1024` |

### Maximum Overdrive (~$0.15-0.40/round)
| Model | Config |
|-------|--------|
| Claude Opus 4.6 | `thinking: {type: "adaptive"}`, `max_tokens: 32000` |
| GPT-5.4 | `reasoning_effort: "high"`, `verbosity: "high"`, `max_tokens: 2048` |
| Gemini 3.1 Pro | `temperature: 1.0`, `thinking_level: "high"` (Deep Think Mini), `top_p: 0.95`, `max_tokens: 4096` |
| Grok 4.20 (`grok-4.20-reasoning`) | `temperature: 0.9`, `max_tokens: 2048` |

## Two Anchor Modes

- **Knowledge anchor** — Claude goes last. Order: Grok -> GPT -> Gemini -> Claude.
- **Abstract anchor** — Gemini goes last. Order: Grok -> GPT -> Claude -> Gemini.

## Three Protocols

### Roundtable (default)
Sequential round-robin. Each model sees all previous responses. The anchor goes last.

### Blind -> Synthesis
All models answer independently in parallel. The anchor synthesizes.

### Debate
Three-phase: proposers (parallel, blind) -> critic (anonymized proposals) -> arbiter (full attribution). User-assignable roles via clickable P/C/S badges.

## CRITICAL: Temperature Rules

- **Claude:** Cannot set temperature when `thinking` is enabled.
- **GPT-5.4:** Temperature locked at 1. Only `reasoning_effort` matters.
- **Gemini 3.1 Pro:** Temperature must be 1.0. Below causes looping.
- **Grok 4.20:** Free parameter (0.0-2.0).

## Routes

| Method | Path | Description |
|--------|------|-------------|
| POST | `/chat` | Send a message, returns conversation_id |
| GET | `/chat/stream/{conv_id}` | SSE stream of model responses |
| GET | `/conversations` | List conversations |
| GET | `/conversations/{id}` | Get full conversation with messages + provenance |
| GET | `/conversations/{id}/export` | Download conversation as markdown (includes compacted messages) |
| POST | `/conversations/{id}/compact` | Manually trigger compaction |
| GET | `/context` | Get current shared context document (legacy) |
| POST | `/context` | Update shared context document (legacy) |
| GET | `/memory` | Get memory index + all topic files + stats + provenance |
| GET | `/memory/{key}` | Get one topic file with provenance |
| PUT | `/memory/{key}` | Update one topic file (sets provenance to manual/user) |
| POST | `/memory/dream` | Trigger AutoDream consolidation pass |
| GET | `/memory/dreams` | List all dream logs |
| GET | `/memory/dream/{id}` | Get specific dream with proposed changes |
| POST | `/memory/dream/{id}/apply` | Apply user-approved dream changes |
| POST | `/memory/dream/{id}/reject` | Reject all dream changes |
| POST | `/import/{platform}` | Upload a chat export (chatgpt, gemini, claude) |

Auth: Bearer token via `Authorization` header or `?token=` query param.

## SSE Event Format

```
data: {"type": "compaction", "messages_compacted": 14, "summary_tokens": 850}
data: {"type": "context_loaded", "topics": ["thesis", "projects"]}
data: {"type": "model_start", "model": "claude", "name": "Claude Sonnet 4.6", "protocol_role": "proposal"}
data: {"type": "token", "model": "claude", "delta": "Hello"}
data: {"type": "model_done", "model": "claude", "content": "full response", "protocol_role": "proposal"}
data: {"type": "model_error", "model": "claude", "error": "timeout"}
data: {"type": "round_done", "context_tokens": 12000, "context_limit": 30000}
```

SSE responses include `Cache-Control: no-cache`, `X-Accel-Buffering: no`, and `Connection: keep-alive` headers.

## Project Structure

```
roundtabllm/
├── CLAUDE.md
├── README.md
├── Procfile
├── railway.toml
├── requirements.txt
├── .env.example
├── .gitignore
├── .railwayignore
├── context/
│   └── jack_context.md         <- seed context (legacy monolithic)
├── backend/
│   ├── __init__.py
│   ├── main.py                 <- FastAPI app, all routes, static file serving
│   ├── config.py               <- env vars, model configs, mode definitions
│   ├── models.py               <- SQLModel schemas (Conversation, Message, ContextDoc, MemoryFile, DreamLog, RawImport)
│   ├── database.py             <- SQLite setup, migrations, memory seeding
│   ├── requirements.txt
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── router.py           <- protocol orchestrator + SSE + auto-compaction
│   │   ├── claude.py           <- Anthropic client + ThinkingStream
│   │   ├── openai_client.py    <- GPT-5.4 client
│   │   ├── gemini.py           <- Google GenAI client + thinking_config
│   │   └── grok.py             <- Grok 4.20 client (OpenAI-compat via xAI)
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── relevance.py        <- keyword-based topic relevance detection
│   │   ├── autodream.py        <- AutoDream memory consolidation engine
│   │   ├── compaction.py       <- conversation compaction pipeline
│   │   ├── memory_index.md     <- seed: topic pointer index
│   │   ├── identity.md         <- seed: who Jack is
│   │   ├── thesis.md           <- seed: academic work, PhD, MAAT
│   │   ├── projects.md         <- seed: active projects, business ideas
│   │   ├── health.md           <- seed: health, supplements
│   │   ├── family.md           <- seed: family, Chickasaw Nation
│   │   ├── tech.md             <- seed: hardware, Tesla, network
│   │   └── work_style.md       <- seed: communication style, priorities
│   ├── context/
│   │   ├── __init__.py         <- context assembly, relevance resolution, system prompts
│   │   └── engine.py           <- distillation pipeline (stub for Phase 5)
│   ├── importers/
│   │   ├── __init__.py
│   │   ├── chatgpt.py
│   │   ├── gemini.py
│   │   └── claude_export.py
│   └── static/                 <- Vite build output
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── main.jsx
│       ├── App.jsx              <- state management, toggles, tab routing
│       ├── api.js               <- fetch wrappers (chat, memory, dream, compact)
│       ├── hooks/
│       │   └── useSSE.js        <- SSE hook (compaction + context events)
│       └── components/
│           ├── ChatView.jsx          <- messages + input + context pressure bar
│           ├── MessageBubble.jsx     <- styled message + provenance badges
│           ├── ModelChips.jsx        <- model toggles + debate roles
│           ├── ModeToggle.jsx        <- Regular / Overdrive
│           ├── AnchorToggle.jsx      <- Knowledge / Abstract
│           ├── ProtocolToggle.jsx    <- Roundtable / Blind / Debate
│           ├── ContextModeToggle.jsx <- Full / Select / None context mode
│           └── ContextEditor.jsx     <- Memory Topics + AutoDream + Raw Context
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

- SQLite not Postgres (personal tool, zero config, Railway persistent volume)
- SSE not WebSockets (simpler, one-way streaming)
- Memory-as-hint not monolithic injection (scalable, cost-bounded)
- Keyword relevance not embeddings (simple, fast, no dependencies)
- AutoDream proposes but never auto-applies (user always reviews)
- Provenance on everything (defense against context poisoning)
- Compaction threshold at 30K tokens (conservative, leaves room for system prompt + context)
- Compacted messages stay in DB (full audit trail for export and AutoDream)
- Temperature fixed at 1.0 for Claude/GPT/Gemini — thinking/reasoning params are the control knobs
- Grok 4.20 reasoning (not multi-agent — multi-agent requires Responses API, not Chat Completions)

## Style Notes

- Dark UI with amber/gold (#D97706) as primary accent
- Model colors: Claude = amber (#D97706), GPT = green (#10B981), Gemini = indigo (#6366F1), Grok = pink (#EC4899)
- Monospace font for chat (JetBrains Mono), display font for headers (Sora)
- Provenance badges: derived = cyan, imported = purple, system = gray (only shown for non-default tiers)
- Context pressure bar: green < 70%, amber 70-90%, red > 90%
- AutoDream changes: ADD = green, UPDATE = amber, DELETE = red with diff-style rendering

## Built With

This application was built entirely by Claude Code. All four models (Claude Sonnet/Opus 4.6, GPT-5.4, Gemini 3.1 Pro, Grok 4.20) are used as participants in the roundtable.
