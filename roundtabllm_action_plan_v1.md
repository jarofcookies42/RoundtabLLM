# RoundtabLLM — Verified Bugs, Features, and Hosting Plan

All findings verified against source at `/Users/Jack/Desktop/llm-roundtable` (same commit as github).

---

## Correction from earlier analysis

I previously said the blind→debate drift was probably caused by an accidental click on the ProtocolToggle. You said you didn't click it. You're right, and the simpler explanation is this:

**What you saw in blind mode was blind mode's actual specified behavior, *with one model silently failing*.** `run_blind` is "N-1 models parallel → anchor synthesizes." If you had 4 models enabled, that's 3 parallel + Claude synth. If one of those 3 parallel models silently failed (zero tokens emitted), you'd see 2 parallel + Claude synth, which has the same visible shape as debate (proposers → arbiter). Same incident as your "one model wasn't responding" observation — it's one bug, not two.

The theoretical protocol-drift vulnerability (backend rewrites `conv.protocol` on every continuation) is still real but apparently not what you actually experienced. Keeping it on the list at lower priority.

---

## Highest-priority bug: silent model failures

**Root cause:** `App.jsx`'s `onModelDone` handler only updates a message bubble that was already created — and message bubbles are only created in `onToken`. If a model opens its stream and emits zero tokens before closing (rate-limit empty body, content-filter rejection, provider outage, timeout before first token, transient API error), the flow is:

1. `model_start` arrives → typing indicator shows
2. Zero `token` events → no message bubble created
3. `model_done` arrives with empty content → `.map` finds no `_streaming` message to update → silently discarded
4. Next model starts → typing indicator moves on

The failed model vanishes. No error, no empty bubble, nothing. Plus, if the backend's exception handler fires at all (which it does for most real errors), the `onModelError` path creates an inline "⚠ error" bubble — but some classes of failures never raise; they just return empty streams.

**Fix in three places:**

1. **Frontend `onModelDone` and `onModelStart`:** On `model_start`, pre-create a streaming placeholder bubble so there's always something for `onModelDone` to land on. Or detect empty `content` in `onModelDone` and surface "⚠ No response from {model}" explicitly.

2. **Frontend `onModelError`:** Currently it only creates a bubble if no tokens arrived yet. Should always show error inline plus (when the error toast system exists) also toast it with provider name and error code.

3. **Backend `router.py`:** When a call completes with empty `full_response`, yield a `model_error` event with a meaningful message ("Provider returned empty response — possible rate limit or content filter") rather than a cheerful `model_done` with no content.

**And the error-forwarding request:** when the API raises with a status code (429, 400, 500), surface that. Right now the backend does `error_msg = str(e)` which may or may not include the code depending on the exception shape. Wrap each client's `call_stream` with an adapter that extracts `{"status": N, "provider_message": "...", "type": "rate_limit/content_filter/timeout/..."}` and pass that structured info through the SSE `model_error` event so the frontend can show "Gemini: rate limited (429)" instead of a truncated stack trace.

---

## All confirmed bugs (verified in code)

### BUG 1 — Silent model failures (see above)
Priority: 🔥 HIGH. The most user-visible bug; directly ties to your observed incidents.

### BUG 2 — User message duplicated in every round
`router.py`: `_load_conversation_history()` pulls the just-saved user message, then it's explicitly appended again. Affects all three protocols. Every round you've run.

Priority: 🔥 HIGH. Fix: either exclude the latest user message from history loading, or don't save it in `POST /chat` and let the router save after loading.

### BUG 3 — Shift+Enter doesn't insert newline
`ChatView.jsx`: the input is `<input ref={inputRef}>`, which is a single-line element. Shift+Enter in a single-line input does nothing — there's nowhere for a newline to go. The `handleKeyDown` logic correctly ignores shift+enter; the element itself just can't display multi-line content.

Priority: 🔶 MEDIUM (you explicitly flagged it). Fix: convert the input to `<textarea>` with auto-growing rows. Keep the same submit-on-Enter, newline-on-Shift+Enter behavior. Maybe 30 minutes of work.

### BUG 4 — Conversation title never set
`main.py` creates conversations with the default "New conversation" title; nothing ever overwrites it. Confirmed in your local db — your one conversation there has that exact default.

Priority: 🔶 MEDIUM. See the "Thread history" section below for the recommended titling strategy.

### BUG 5 — Protocol overwritten on every continuation (theoretical)
Backend rewrites `conv.protocol = req.protocol` on every continuation without a guard. ProtocolToggle is always clickable in the header, cycles (not a selector). Not the cause of your observed incident, but still a real vulnerability — one accidental click and a conversation silently changes protocol forever.

Priority: 🟡 LOW-MEDIUM. Fix: backend writes only on first message; frontend disables toggles once `conversationId` is set.

### BUG 6 — Import endpoint parses but doesn't save conversations
`POST /import/{platform}` saves raw JSON to `RawImport` but never inserts parsed conversations into `Conversation`/`Message`. Can't confirm against your prod data without pulling the Railway db; local db has 0 `RawImport` rows so no useful data there.

Priority: 🔶 MEDIUM.

### BUG 7 — AutoDream ingests error messages
`autodream.py` query for recent messages lacks `is_error == False`. Any "⚠ Error: ..." strings get fed into dream transcripts.

Priority: 🔶 MEDIUM. One-line fix.

### BUG 8 — `conv.updated_at` never refreshed on continuation
Matters once the sidebar exists because sort order will be wrong.

Priority: 🟡 LOW. One-line fix.

### BUG 9 — Dream lock has no timeout
Crashed dream → permanent pending → all future dreams blocked.

Priority: 🟡 LOW.

### BUG 10 — Memory cap enforced after the fact, not before
`apply_dream_changes` returns a warning after overshoot instead of preventing it.

Priority: 🟡 LOW.

### BUG 11 — PDF attachments garble to mojibake
`ChatView.jsx` lines 48-54 read PDFs as text in both branches. Interestingly, as you noted, models are sometimes resilient enough to parse meaning out of the garbage. But it's unreliable. Fix options: reject with a clear error, or do server-side extraction via `pypdf`/`pdfplumber` and attach the extracted text instead.

Priority: 🟡 LOW (works-enough for your current usage).

### BUG 12 — Single shared auth token
Fine for you. Hard blocker for multi-user.

Priority: Deferred until multi-user.

---

## Thread history — per your preferred design

You said: title by date/time of last message, with option to rename. Works well. Implementation:

**Backend:**
- `GET /conversations` already exists, sort by `updated_at.desc()`.
- Add `PATCH /conversations/{id}` that accepts `{title: "..."}`.
- Add `DELETE /conversations/{id}` — soft-delete (add `archived` bool to the model) to preserve dream-pass history.
- Auto-title: on first user message, set `conv.title = conv.updated_at.strftime("%b %d, %I:%M %p")` — e.g., "Apr 21, 4:12 PM". After that, update `conv.title` only if user explicitly renames (don't auto-update to keep it stable once set).

Actually, reconsidering: auto-updating the title to reflect the *last* message time (as you originally suggested) has a nice property — you can see at a glance which threads are active. But it loses the stable identifier feel. Recommendation: use `updated_at` for the sort order (which already happens), show that timestamp next to the title in the sidebar, and let the title itself be either user-set or a preview of the first user message. That matches how ChatGPT/Claude/Gemini all handle it — title is derived from content, sort is by recency, and both are visible.

**Frontend:**
- New component `ConversationSidebar.jsx`. Collapsible left panel (desktop) / drawer (mobile). List of `{title, updated_at, preview of first message}`. Search input filters by title. Right-click or hover-menu for rename/delete.
- On conversation click: fetch `GET /conversations/{id}`, hydrate `messages[]`, `conversationId`, **and** the conversation's stored `protocol/mode/anchor/contextMode/selectedTopics`. This incidentally also closes Bug 5 — once you're loading conversation state properly, the backend won't see mismatched protocols on continuation.

---

## UX parity checklist vs ChatGPT / Claude / Gemini / Grok

You said you want it to feel like those apps. Here's what they all have that you don't yet:

**Must-have for feeling like a real chat app:**
- [ ] Sidebar with conversation history, search, rename, delete (thread history)
- [ ] Multi-line input with Shift+Enter for newline (Bug 3)
- [ ] Copy button on each message
- [ ] Regenerate button on assistant messages (in your case, per-model regenerate)
- [ ] Clear visual feedback when a model fails (Bug 1)
- [ ] Edit-and-resend for user messages (less essential but expected)
- [ ] Auto-scroll to new messages (you have this)
- [ ] Streaming token rendering (you have this)

**Niceties those apps have that make sense for you:**
- [ ] Stop-generation button (mid-round cancel)
- [ ] File attachments that actually work (Bug 11)
- [ ] Markdown rendering in responses (you may have this — I didn't check MessageBubble)
- [ ] Code block syntax highlighting (same)
- [ ] Keyboard shortcuts for new chat (Cmd+N style)

**Your unique features worth keeping visible:**
- Protocol toggle — but once conversation is live, lock it (Bug 5 fix)
- Mode/anchor toggles — same
- Model chips with role assignment for debate
- Memory/context tab
- Compaction notice
- Context pressure indicator

**Things those apps have that you should NOT copy:**
- Hidden/obscured system prompts (yours are transparent by design)
- Single-model framing (your value is the multi-model comparison)
- "Thought process" hidden by default (your thinking capture is a feature)

---

## Railway → alternative hosting

### The SQLite problem (reminder)
Your real db is on Railway's persistent volume. Most cheap container hosts have ephemeral filesystems. Moving without a volume = wiping everything.

### Recommended path
1. **This week:** Fly.io with a volume. Lowest-risk exit from Railway. Needs a Dockerfile (you don't have one, only Procfile + railway.toml). Claude Code can generate it from your requirements.txt and FastAPI setup.
2. **Before inviting other users:** Postgres migration + real auth (Bug 12). SQLite + shared token won't survive real users.
3. **Fallback:** self-host on your desktop via Cloudflare Tunnel.

### Pre-migration checklist
- [ ] Back up `roundtable.db` from Railway to somewhere off-Railway **this week**, regardless of when you move.
- [ ] Dump `RawImport` separately so the eventual Bug 6 fix has source material.
- [ ] Export memory files via `GET /memory` (saves as JSON).
- [ ] Save Railway env var list.
- [ ] Confirm all four API keys are in env, not hardcoded.

### Dev vs prod db (for reference)
Your local `roundtable.db` has 1 conversation, 1 message, 0 imports, 0 dreams, 8 seed memory topics. This is clearly a dev copy — your production data lives on Railway. Any meaningful db analysis has to happen on the Railway copy.

---

## Suggested execution order

Given V&V is the academic priority and Railway deadline is looming:

**Session A — this week, stop the bleeding (2-3 hrs):**
- Back up Railway db to external storage
- Set up Fly.io with volume, test deploy with db copy

**Session B — critical bugs (1-2 hrs):**
- Bug 1: silent model failures — pre-create placeholder bubble on model_start, handle empty model_done, surface provider error codes
- Bug 2: message duplication
- Bug 7: AutoDream error filter

**Session C — thread history foundation (2-3 hrs):**
- Bug 4: conversation auto-titles + Bug 8: `updated_at` refresh
- Backend: PATCH rename, DELETE archive
- Frontend: ConversationSidebar + full conversation load (protocol state hydration closes Bug 5 too)

**Session D — input polish (1 hr):**
- Bug 3: input → textarea with shift+enter
- Copy button on messages
- Regenerate button per model

**Session E — pre-multi-user (bigger lift, 4-6 hrs):**
- Bug 12: real auth (OAuth or magic links)
- Bug 6: import endpoint actually saves conversations
- Bug 11: PDF proper handling
- Postgres migration
- Protocol/mode/anchor toggles disabled once conversation is live (full Bug 5 fix)

**Session F — product polish when thesis allows:**
- Stop-generation mid-round
- Error toast system
- Forced dissent, thinking sliders, divergence heatmap, CoT leakage

---

## Things I can do in follow-ups

1. **Read MessageBubble.jsx** — confirm whether markdown/code highlighting is already there.
2. **Inspect your Railway db** — if you dump it somewhere I can read (or bring it local), I can give real counts: how many conversations, how many imported conversations (confirm Bug 6), how many silent-failure messages (empty content + `is_error=False`), dream history, memory growth over time.
3. **Read one LLM client** (e.g., `grok.py` or `gemini.py`) — to see if there's a known path that yields an empty stream without raising. Useful for confirming the Bug 1 mechanism precisely.
4. **Read the raw importer modules** — to design the Bug 6 fix correctly (know the exact shape of parsed conversations).

Say which would be most useful next.
