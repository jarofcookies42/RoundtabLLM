# RoundtabLLM — Context Handoff

Compiled April 21, 2026 at the end of a long planning conversation. Purpose: seed a new Claude chat thread so Jack can continue RoundtabLLM design work and Claude Code prompt drafting without losing what we established. All findings here were verified against real source code and a production database dump — treat them as ground truth rather than re-investigating.

---

## TL;DR for the new thread

- RoundtabLLM is Jack's multi-model AI deliberation app (Claude + GPT + Gemini + Grok). FastAPI + React + SQLite. Currently on Railway; trial ending ~April 23.
- Production database backed up locally at `~/Desktop/roundtabllm-backup-20260421.tar.gz` (272KB uncompressed, 5 conversations, 133 messages). Backup is safe.
- Several bugs have been verified in source code. Priority-ordered list below.
- Several features are wanted; priority-ordered list below.
- **Major architectural reframe in play:** Jack now says the app was always intended to be reusable by classmates/teachers, not a personal tool. This changes the auth + user + memory-namespacing story materially. Open design question — see the "Reframe" section.
- V&V Final Report is Jack's actual top academic priority right now. RoundtabLLM work must not cannibalize it.

---

## What the app is and how it's architected

RoundtabLLM is a multi-model chat interface where several LLMs respond to the same prompt in one of three protocols:

- **Roundtable** — sequential round-robin; each model sees all prior responses; anchor goes last.
- **Blind → Synthesis** — all non-anchor models respond in parallel without seeing each other; anchor synthesizes.
- **Debate** — two proposers respond in parallel (blind), a critic reviews them anonymized, an arbiter synthesizes with full attribution.

Two modes:
- **Regular** — lighter/cheaper model tier (Claude Sonnet, etc.). ~$0.02/round.
- **Maximum Overdrive** — premium tier. ~$0.15–0.40/round. Currently uses Claude Opus 4.6. **Jack wants this updated to Opus 4.7** (this was explicitly called out to remember — it's on the feature list below).

Two anchor orders:
- **Knowledge:** `[grok, gpt, gemini, claude]` — Claude last (anchors with comprehensive knowledge synthesis)
- **Abstract:** `[grok, gpt, claude, gemini]` — Gemini last (anchors with more abstract/creative synthesis)

Three context modes: `full` (load all memory), `select` (user picks topic files), `none` (blank context).

Memory system: 8 topic files (`identity`, `thesis`, `projects`, `tech`, `family`, `health`, `work_style`, plus an `index` file used for keyword routing). Memory-as-hint pattern — the relevance resolver picks topic files based on recent user messages and feeds them as context. 25KB / 200-line hard cap. AutoDream is a separate "consolidation pass" that proposes updates to topic files based on recent conversations; user reviews and approves diff.

Compaction: when context pressure is high, older messages are summarized into a single compaction summary and marked `compacted=True` so they're excluded from live context but preserved in the DB.

Repo layout (at `/Users/Jack/Desktop/llm-roundtable/`):
- `backend/main.py` — FastAPI endpoints
- `backend/models.py` — SQLModel schema (Conversation, Message, MemoryFile, DreamLog, RawImport, ContextDoc)
- `backend/llm/router.py` — three protocol functions (`run_round`, `run_blind`, `run_debate`)
- `backend/llm/{claude,openai_client,gemini,grok}.py` — per-provider client wrappers
- `backend/memory/autodream.py` — dream consolidation
- `backend/memory/compaction.py` — compaction
- `backend/context/__init__.py` — context resolution (memory-as-hint)
- `backend/importers/` — parsers for ChatGPT, Gemini, Claude exports
- `frontend/src/App.jsx` — main state + SSE wiring
- `frontend/src/components/{ChatView,MessageBubble,ModelChips,ProtocolToggle,ModeToggle,AnchorToggle,ContextEditor,ContextModeToggle}.jsx`
- `frontend/src/hooks/useSSE.js` — SSE event handling
- `frontend/src/api.js` — API client
- `context/jack_context.md` — comprehensive briefing compiled March 25 from ~2 months of Claude conversations; this is what the 8 memory topic files were manually sliced from
- `CLAUDE.md` — project conventions, temperature rules, anchor order reference, etc. **New Claude Code sessions must read this first.**
- `roundtable.db` — local SQLite (mostly empty, test data only)

---

## Verified bugs (priority ordered)

All verified by reading source code and/or querying the production database dump. Evidence cited where applicable.

### 🔥 BUG 1 — Silent model failures
**Priority:** Critical — actively corrupting observed behavior.

**Where:** `frontend/src/App.jsx` (onModelStart/onModelDone/onModelError callbacks) and `backend/llm/router.py` (all three protocol functions).

**Root cause:** Message bubbles on the frontend are only created inside the `onToken` handler. If a model opens its stream and closes without emitting any tokens (provider rate-limit empty body, content filter rejection, timeout before first token, transient 5xx without raising), the flow is:

1. `model_start` event → typing indicator shows
2. Zero `token` events → no bubble is ever created
3. `model_done` event with empty content → `.map` finds no `_streaming` message to update → silently discarded
4. Next model starts → typing indicator moves on

No error shown. No bubble. The model "vanishes" from that round.

**Secondary issue:** When exceptions ARE raised, the backend does `error_msg = str(e)` which usually loses the HTTP status code, provider message, and error type (rate limit vs content filter vs timeout).

**Evidence from prod DB:**
- 3 messages in the `message` table with `is_error=0` and empty/null `content` — these are silent failures that got saved as valid messages.
- Claude has 25 messages vs 27 for each other model across 27 rounds. 2 rounds Claude didn't even reach `_save_msg`.
- This explains Jack's observation that "in blind mode, it turned into debate mode" — it was blind mode working correctly with one model silently failing, making 3 parallel models look like 2 proposers + Claude synthesizing (which visually mimics debate structure).

**Fix sketch:** Frontend pre-creates a placeholder bubble on `model_start`. Frontend detects empty content in `model_done` and renders as inline error. Backend adds a `_format_provider_error(exc)` helper that extracts structured info (`{error, error_type, status_code, provider_message}`) for Anthropic/OpenAI/Gemini exception types. Backend yields structured `model_error` events including empty-stream detection.

### 🔥 BUG 2 — User message duplicated in every round
**Priority:** Critical — corrupts context for every LLM call ever made.

**Where:** `backend/llm/router.py`, all three protocol functions. Same exact pattern:

```python
round_messages = _load_conversation_history(conversation_id, session)
round_messages.append({"role": "user", ..., "content": user_message})
```

`_load_conversation_history()` pulls all non-compacted messages. By the time it runs, `POST /chat` has already saved the current user message. So the message is in history *and* gets appended explicitly. Every round, every model, since the app was built.

Some models flag this behavior ("I see your message twice") which is how Jack noticed. Stricter models probably silently deduplicate or get subtly confused without flagging.

**Fix sketch:** Move the user message save out of `POST /chat` and into the stream handler, after `_load_conversation_history()` runs. Pass `user_message` as a query param on the SSE endpoint. Save once, append once.

### 🔶 BUG 3 — Shift+Enter doesn't insert newline
**Priority:** Medium — UX blocker.

**Where:** `frontend/src/components/ChatView.jsx`. The composer is an `<input>` element. The `handleKeyDown` correctly checks `!e.shiftKey` before submitting, but single-line `<input>` physically cannot hold newlines.

**Fix sketch:** Replace with `<textarea>` that auto-grows.

### 🔶 BUG 4 — Conversation title never set
**Priority:** Medium — becomes critical once thread history sidebar is built.

**Where:** `backend/main.py` `POST /chat`. Creates a `Conversation` without a title; the default is literally `"New conversation"` per `models.py`. Nothing ever overwrites it.

**Evidence:** All 5 conversations in the production DB have `title="New conversation"`.

**Fix sketch:** On first user message only, set `conv.title = req.message[:50] + ("..." if len(req.message) > 50 else "")`. Stable after that unless explicitly renamed.

### 🟡 BUG 5 — Protocol/mode/anchor overwritten on every continuation
**Priority:** Low-medium — theoretical; not the cause of the "blind turned into debate" incident (that was Bug 1).

**Where:** `backend/main.py` `POST /chat` continuation block. Unconditionally rewrites `conv.mode/anchor/protocol/context_mode/selected_topics` from the request on every message.

**Mechanism:** Frontend's ProtocolToggle is a cycling button always live in the header. One accidental mid-thread click would silently change the conversation's protocol forever. Not confirmed to have happened to Jack, but the vulnerability is real.

**Fix sketch:** Backend only writes these fields on first message (new conversation). On continuation, log a warning on mismatch and use stored values. Frontend disables toggles once `conversationId` is set, and hydrates from conversation state when loading an existing thread.

### 🟡 BUG 6 — `conv.updated_at` never refreshed on continuation
**Priority:** Low — matters once thread history sidebar exists.

**Where:** Same block as Bug 5. Other fields get written; `updated_at` does not. `GET /conversations` sorts by `updated_at.desc()`, so resumed conversations won't bubble to top.

**Fix sketch:** Add `sa_column_kwargs={"onupdate": datetime.utcnow}` to the `updated_at` field in `models.py`.

### 🟡 BUG 7 — AutoDream ingests error messages
**Priority:** Low — minimal real-world impact.

**Where:** `backend/memory/autodream.py`, the "Load all messages for these conversations" query lacks `is_error == False` filter.

**Real impact:** AutoDream has run exactly once in 2 weeks of prod usage, and that run didn't encounter error messages. So the bug hasn't actively harmed memory yet. Still worth fixing.

**Fix sketch:** One-line filter add.

### 🟡 BUG 8 — Dream lock has no timeout
**Priority:** Low.

**Where:** `backend/memory/autodream.py` and `backend/main.py`. Both check `DreamLog.status == "pending"` with no age check. Crashed dream → permanent pending → blocks all future dreams.

**Fix sketch:** Mark dreams older than 30 minutes as failed before checking for pending.

### 🟡 BUG 9 — Memory cap enforced after the fact, not before
**Priority:** Low.

**Where:** `apply_dream_changes()` in `autodream.py`. Computes totals *after* applying, returns a `warning` string if over cap.

**Fix sketch:** Project totals forward before applying; reject the operation if it would overshoot.

### 🟡 BUG 10 — PDF attachments read as mojibake
**Priority:** Low — Jack notes that "models are able to view it correctly funny enough," so this works in practice. Still unreliable.

**Where:** `frontend/src/components/ChatView.jsx` — both branches of the PDF check call `reader.readAsText(file)`. PDFs get binary-decoded as text.

**Fix sketch:** Either reject PDFs with a clear error, or add server-side extraction via `pypdf`/`pdfplumber`.

### ⏸ BUG 11 — Single shared auth token
**Priority:** Deferred until multi-user is imminent — see "Reframe" section below.

**Where:** Whole app. `AUTH_TOKEN` env var + `verify_auth` dependency. Anyone with the token is "Jack" to the system.

Fine for personal use. Hard blocker for multi-user. Not a bug *now*; will become one the moment someone else tries to use the app.

### ⏸ BUG 12 — Admin backup endpoints still in source code (housekeeping)
**Priority:** Low but should be cleaned up soon.

**Where:** `backend/main.py`. Two endpoints (`GET /admin/backup-db` and `GET /admin/backup-all`) were added April 21 for a one-time Railway export. The `ENABLE_ADMIN_BACKUP` env var is off on Railway (and the endpoints return 404 without it), but the code is still present. Should be removed in a cleanup commit.

---

## Non-bugs (do not re-investigate these)

GitHub Copilot (running Haiku 4.5) did a triple-pass analysis earlier that produced about 30 claimed bugs. Verification against actual code showed roughly 1/3 were real, 1/3 were cosmetic or irrelevant, and two were outright hallucinations. For the new thread's benefit, here are the ones already confirmed NOT to be bugs, so we don't waste time revisiting:

- **"Grok client missing / app will crash"** — `backend/llm/grok.py` exists and works. Hallucination.
- **"Compaction summary never created"** — Copilot self-retracted on pass 3; code is correct.
- **"Import endpoint doesn't save parsed conversations"** — The `/import/{platform}` endpoint parses and returns counts but doesn't insert `Conversation`/`Message` rows. This was flagged as a bug. It isn't. Per Jack's own design, the imports were always intended to feed a distillation pipeline (produce memory topic file updates), not to become browseable conversations. The current scaffolding is an unbuilt future feature. `RawImport` has 0 rows in production anyway — the 8 memory topic files were seeded manually from `context/jack_context.md`, bypassing this pipeline entirely.
- **"Debate 3-model role assignment conflict"** — Walking through the logic shows roles resolve correctly to (proposer, critic, synthesizer). The overwrite pattern looks suspicious but converges correctly. Latent issue exists for 5+ model debates (slot 3 unassigned) but that configuration isn't used.
- **"No backend rate limiting / debate role validation"** — Defensible in principle but irrelevant at current scale with one user.
- **"Temperature config not enforced"** — The code is actually correct; Copilot was asking for defensive validation, not fixing a real bug.
- **"Batch message merging inconsistency across providers"** — Didn't verify, low priority; the router doesn't produce consecutive same-role messages in practice.
- **"Relevance detection always loads work_style"** — Minor context waste; not a bug.

---

## Features wanted (rough priority order)

### Must-have before opening to other users (see Reframe section)

1. **Conversation history sidebar.** Jack's top-requested feature. Current app has NO way to see or load past conversations from the UI. Backend has `GET /conversations` and `GET /conversations/{id}` endpoints already; nothing consumes them. Needs:
   - Left sidebar (drawer on mobile) showing conversations sorted by `updated_at` desc
   - Title, relative timestamp, mode/protocol badges
   - Search by title (frontend filter)
   - Rename, delete (soft-delete via new `archived` field)
   - Click to load: hydrate `messages`, `conversationId`, `mode`, `anchor`, `protocol`, `contextMode`, `selectedTopics` from the conversation
   - Requires Bug 4 (titles) fixed first or it's useless

2. **Message timestamps.** `Message.created_at` exists in the schema. `GET /conversations/{id}` response doesn't include it, frontend state doesn't track it, `MessageBubble` doesn't render it. Three touch points, not hard. Jack is not super worried about timestamps as a standalone feature but they should come along with the history sidebar naturally.

3. **Multi-line input with Shift+Enter (Bug 3 fix).**

4. **Copy button on each assistant message.**

5. **Regenerate button per model.** One-click re-run of a single model on the same context. Essential when a model errors out but others finished fine, or when the user wants a different take without redoing the whole round.

6. **Error toast system.** Currently model errors become inline `⚠ ...` bubbles that look like responses. Errors should be toasts; inline bubbles should be reserved for actual content. Pairs with the Bug 1 fix.

7. **Protocol/mode/anchor lock UI.** Once a conversation is live, disable the toggles (or visually lock them with a tooltip: "locked — start a new conversation to change"). Backend half is Bug 5.

8. **Real auth.** Bug 11. See Reframe.

### Currently stubbed in TODOs; worth actually building

9. **Forced dissent toggle.** System prompt append that requires the model to disagree with or challenge at least one point in prior responses. Low-effort, high payoff for debate quality. Already stubbed.

10. **Per-model thinking/reasoning sliders.** Claude `thinking_budget`, GPT `reasoning_effort`, Gemini `thinking` level. High leverage for Maximum Overdrive tuning. Already stubbed.

11. **Divergence heatmap.** Visual representation of how much the models disagree per round. Great demo piece for Dr. Namin. Already stubbed.

12. **CoT leakage monitor.** Detect when thinking content is leaking into final output. Directly ties to Jack's thesis on adversarial trustworthiness testing. Already stubbed.

### Config update Jack wants to remember

13. **Upgrade Maximum Overdrive to Claude Opus 4.7.** Currently uses 4.6. The model string `claude-opus-4-7` needs to go into `backend/config.py`. Also worth auditing the config module for any other stale model names and refreshing as appropriate.

### Deferred / require design conversation first

- **Stop-generation mid-round.** UX pattern from ChatGPT/Claude that lets the user abort a running round. Requires cancellation plumbing through SSE streams.
- **Edit-and-resend for user messages.** Common pattern in big chat apps.
- **Markdown rendering and code block syntax highlighting.** Unknown if already present in `MessageBubble.jsx`; worth a quick check.
- **Keyboard shortcuts** (Cmd+N for new chat, etc.).
- **Distillation pipeline.** Ties directly into the multi-user reframe; see below.
- **Postgres migration.** Required before multi-user.
- **BYOK (bring your own keys).** Required if other users are going to use the app without Jack eating their API costs. See Reframe.
- **PDF handling properly** (Bug 10).

---

## The big reframe — single-user vs reusable tool

Jack's framing for the project shifted late in the planning conversation. Originally described as a personal tool, he clarified that RoundtabLLM was always intended to be **reusable by classmates and teachers** who also use multiple LLMs and want their own personalized roundtables. This changes more than it first looks.

### The immediate problem

The 8 memory topic files in production are Jack's personal briefing — his thesis details, medications, family info, project roadmaps. They're loaded into the context of every conversation via the memory-as-hint system. If a classmate signed up tomorrow using the shared auth token, the models would be loading Jack's personal context into the prompts for a stranger. That's a data-leak dressed up as a seed-data issue.

So: **RoundtabLLM isn't a personal tool that might eventually go multi-user. It's a multi-user product that currently has exactly one user.** That's a different architecture conversation.

### What changes architecturally

1. **Auth.** Bug 11 stops being "deferred until later" and becomes foundational. OAuth (Google or GitHub) is easiest for an academic audience — classmates already have those accounts.

2. **User model + ownership fields.** Every row in `Conversation`, `Message`, `MemoryFile`, `DreamLog`, `RawImport` needs a `user_id`. Migration: existing rows go to a `user_id=1` "Jack" user.

3. **Memory namespacing.** Either `user_id` on `MemoryFile` or per-user memory tables. Seed files concept changes — new users have empty memory, not Jack's.

4. **Distillation pipeline becomes the onboarding flow.** Currently your 8 topic files were hand-sliced from `jack_context.md` before being seeded. A classmate can't do that — they shouldn't have to write Python. The pipeline becomes: user uploads ChatGPT/Claude/Gemini exports → Claude pass reads and proposes topic files → user reviews/edits → seeded into *their* memory. This is the actual killer feature that makes it a product. It also justifies the existing `RawImport` table and `/import/{platform}` endpoint which currently look like orphaned scaffolding. This is what Jack's own `export-distillation-companion.md` doc was imagining.

5. **API keys.** Options:
   - Jack eats all costs (bad for budget)
   - BYOK — each user provides their own Anthropic/OpenAI/Google/xAI keys (probably right for academic audience since classmates already have API accounts)
   - Paid tier with Jack-provided keys (overkill for thesis-adjacent project)
   - Recommendation leans BYOK.

6. **Postgres migration** becomes required rather than optional. SQLite is single-writer; multi-user traffic will hit it hard.

### Alternative: the self-hostable framing

If "other users can try it" is the real goal rather than "run a multi-tenant service," there's a much cheaper path: keep the app single-user, but package it as self-hostable. A classmate clones the repo, sets their own API keys in `.env`, runs it locally, seeds their own memory files from their own briefing. That's a polished README + setup script + maybe a CLI wrapper for the distillation, not a migration. Less impressive, less "product," but it's a weekend instead of a month.

### The question Jack should resolve before significant design work

**Do classmates need to share Jack's instance, or do they just need access to *something that works like this*?** The answer determines whether the next several sessions build a multi-tenant product or a polished single-user tool that others can run themselves. Both are defensible. The multi-tenant path is roughly 2-3 weekends (auth + namespacing + Postgres + distillation); the self-hostable path is roughly 1 weekend (README + env handling + a setup CLI).

The new thread should start by getting Jack to commit to one framing before drafting prompts.

---

## Hosting status

- **Current:** Railway, SQLite on persistent volume. Trial ends ~April 23 (2 days from April 21).
- **Backup:** Done. File at `~/Desktop/roundtabllm-backup-20260421.tar.gz` on Jack's Mac. Contains `roundtable.db` only (272KB). Verified valid.
- **Endpoint cleanup pending:** The admin backup endpoints (`/admin/backup-db` and `/admin/backup-all`) are still in `backend/main.py`. The `ENABLE_ADMIN_BACKUP` env var is off on Railway so they 404, but the code needs removing in a cleanup commit.

### Recommended migration path

1. **This week (urgent):** Fly.io with a volume. Minimal code change (add Dockerfile, add `fly.toml`, change SQLite path to read from `DB_PATH` env var). Copy the backup to the Fly volume. Smallest machine size, ~$2-5/month.
2. **Before multi-user (if that path is chosen):** Postgres migration. SQLModel handles both; migration script reads from SQLite, writes to Postgres.
3. **Fallback option always available:** Self-host on Jack's desktop PC via Cloudflare Tunnel.

Fly.io migration can happen *before* any bug fixes — the app runs the same on Fly as on Railway. Don't let the two tracks block each other.

---

## Production database snapshot (as of April 21 backup)

Useful grounding for what's actually in the system:

- **5 conversations.** Date range April 2-17. All titled "New conversation" (Bug 4 confirmed).
- **133 messages.** 27 user + 27 grok + 27 gpt + 27 gemini + 25 claude. Claude deficit is silent-failure evidence (Bug 1).
- **1 error-flagged message** (grok).
- **3 non-error empty-content messages** — silent failures where the model yielded zero tokens without raising (Bug 1).
- **8 memory topic files.** All `source="seed"`, `last_modified_by="user"`, `derived_from=NULL`. All timestamped April 2. Never modified since.
- **1 AutoDream log.** April 2, status "approved." Summary said no existing memory needed updating; added a small addition about RoundtabLLM itself to the `projects` file.
- **0 raw imports.** The `/import/{platform}` endpoint has never been used on this deployment. Memory was seeded manually, bypassing the endpoint entirely.
- **0 context docs** (the legacy single-context system has been superseded by the memory files).

**Memory freeze observation:** Your memory is effectively frozen at April 2. AutoDream has run exactly once. As your thesis, Aquifer-Watch, and RoundtabLLM itself evolve, the memory files don't know. Three ways to address when the time comes: manual editing via Memory tab, more frequent AutoDream passes, or periodic re-distillation from a refreshed briefing doc.

**Cross-system memory drift:** The memory files in RoundtabLLM and Anthropic's memory system (in Claude Projects / Claude apps) are separate. Updates to one don't propagate. The closest single-source-of-truth document is `context/jack_context.md` which is frozen at March 25.

---

## How the new thread should operate

### Role

The new thread is for **design conversations and Claude Code prompt drafting.** Not implementation. Jack's Claude Code sessions do implementation. The new thread plans and writes prompts.

### Workflow

1. Jack directs the new thread to a working area (specific feature, bug cluster, or design question).
2. New thread reads relevant files from the repo to confirm current state (don't assume — files drift between sessions).
3. New thread surfaces open design questions and guides Jack to decisions.
4. New thread drafts a Claude Code prompt, scoped tightly with explicit "do NOT" guardrails.
5. Jack pastes into Claude Code on his Mac, verifies result, returns to new thread for next step.

### Prompts doc pattern that works

A prompt block that's worked well:
- Opens with "Read CLAUDE.md first"
- States the exact problem with one-line repro or code reference
- Specifies exactly which files/functions to change and in what way
- Includes "Do NOT" section for anything out of scope
- Asks Claude Code to report back specific things (log format, new URL, commit message, file list)

Example of a well-scoped prompt:

```
---PROMPT START---
Read CLAUDE.md first.

[problem statement with concrete evidence]

Please [specific changes, file by file]:

1. [Change to file A]
2. [Change to file B]
...

Do NOT:
- [Out-of-scope item 1]
- [Out-of-scope item 2]

After you're done, tell me [specific thing to verify].
---PROMPT END---
```

Tight, no ambiguity, verifiable result. Avoid prompts that say "clean up the X module" — those drift.

### What the new thread should NOT do

- Write implementation code directly for Jack to use. Plan and prompt only.
- Frame work as "months of effort" — Jack vibe-codes with Claude Code and moves fast. Weekends, not months.
- Reintroduce Copilot's rejected claims (see "Non-bugs" section above).
- Assume GitHub Copilot is reliable. It runs on Haiku 4.5 and hallucinates.
- Over-invest in features before the multi-user-vs-self-hostable question is answered. That decision changes the shape of everything else.
- Let V&V Final Report work slip. Jack's stated top academic priority is the V&V report. RoundtabLLM is compelling but secondary.

### Verify, don't trust

Jack has a Filesystem MCP connector enabled. Use the `Filesystem:read_file` / `Filesystem:read_text_file` / `Filesystem:list_directory` tools to look at actual source. Do not infer from memory or prior conversations — they drift. The cost of reading a file is near zero; the cost of being wrong is meaningful.

Allowed root is `/Users/Jack` (Mac user directory). Working dir is `/Users/Jack/Desktop/llm-roundtable/`.

---

## Suggested execution order for the new thread

Once Jack answers the multi-user-vs-self-hostable question, a roughly sensible order:

**Phase 0 — housekeeping (1 session, trivial):**
- Remove admin backup endpoints from source code (Bug 12).

**Phase 1 — hosting stability (1 session, this week):**
- Fly.io migration with volume. Dockerfile, `fly.toml`, `DB_PATH` env var, deploy, copy backup up.

**Phase 2 — critical bugs (1-2 sessions):**
- Bug 1: silent failures (frontend + backend + provider error structure).
- Bug 2: message duplication.

**Phase 3 — quick wins bundle (1 session):**
- Bug 4 (titles), Bug 6 (updated_at), Bug 7 (autodream error filter), Bug 8 (dream lock timeout), Bug 9 (memory cap enforcement). Five commits, one session.

**Phase 4 — backend protocol lock (1 session):**
- Bug 5 backend half.

**Phase 5 — the big UX session:**
- Thread history sidebar
- Full conversation load with state hydration (closes Bug 5 frontend half)
- Message timestamps
- PATCH/DELETE endpoints
- `archived` field

**Phase 6 — input polish (1 session):**
- Bug 3 (textarea + Shift+Enter)
- Copy button
- Regenerate button

**Phase 7 — config refresh (small):**
- Opus 4.7 swap in Maximum Overdrive
- Audit other stale model versions in `config.py`

**Phase 8 — contingent on reframe answer:**
- If multi-user: auth + user namespacing + Postgres + distillation pipeline.
- If self-hostable: README + setup CLI + env-handling polish.

**Phase 9 — stubbed thesis-relevant features:**
- Forced dissent, thinking sliders, divergence heatmap, CoT leakage monitor. Pick based on what advances the V&V report and the Dr. Namin demo.

---

## Meta notes about Jack's working style

(Useful for the new thread to calibrate tone and pacing.)

- Casual/conversational tone preferred. No corporate voice.
- Skeptical of unverified claims. Expects evidence, especially after the Copilot analysis exercise demonstrated that confident-sounding bug reports can be half-hallucinated.
- ADHD-prone to ambitious planning without follow-through — watch for over-scoping a single prompt or a single week.
- Budget-conscious. Tools and infrastructure should be cheap.
- Has Claude Max plan; uses Claude Code since March 2026.
- Prefers markdown for planning, `.docx` for formal deliverables.
- Does not want Claude to write implementation code — that's Claude Code's job.
- Family: married, three kids, wife works NICU night shift.
- Academic context: CS grad student at Texas Tech, Chickasaw Nation citizen, working with Dr. Namin (thesis advisor) separately from Dr. Shin (CS5363 instructor) — don't conflate these two.
- V&V Final Report on LLM adversarial testing (seed phrase side-channel analysis) is the top academic priority right now. Everything else is secondary.

---

## Final orientation for the new thread

Start by asking Jack two things:

1. **Which framing is RoundtabLLM?** Multi-tenant product for classmates, or self-hostable tool? The entire Phase 8 plan hinges on this.

2. **What's the immediate priority?** Phase 0-1 (housekeeping + Fly migration) are defensible defaults. But if Jack has a specific bug or feature that's blocking him, start there.

Then follow the execution order and draft tight, scoped prompts. Read the actual source files via Filesystem tools before writing any prompt — code has almost certainly drifted since the last read.

Good luck.
