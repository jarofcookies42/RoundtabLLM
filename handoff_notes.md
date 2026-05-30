# RoundtabLLM — Handoff Notes

This document summarizes the current development state of RoundtabLLM, focusing on model overrides, thinking streams, React callback stability, and documentation alignments.

---

## 1. LLM Thinking/Reasoning Availability

| Model | Slot Key | API Thinking Support | Current Status in App |
| :--- | :--- | :--- | :--- |
| **Gemini 3.1 Pro** | `gemini` | **Supported** (via Vertex/GenAI SDK `include_thoughts`) | **Fully Operational.** Streams thought process blocks dynamically into expanded bubbles. |
| **Claude Opus 4.7** | `claude` | **Supported** (via Anthropic API `thinking` config) | **Partially Operational.** Supported in code and streams, but actual raw text outputs depend on account-level model availability and prompt complexity. When raw thoughts are omitted by the API, it still streams a `signature_delta` continuity block. |
| **GPT-5.4** | `gpt` | **Hidden** (via OpenAI `reasoning_effort` param) | **No exposed text.** Reasoning tokens are processed internally by OpenAI and are billed but hidden from Chat Completions API streams. |
| **Grok 4.20** | `grok` | **Hidden** (in reasoning model) | **No exposed text.** Like OpenAI, Grok's chain-of-thought is hidden from Chat Completions. We toggle between `grok-4.20-reasoning` and `grok-4.20-non-reasoning` under the hood. |

---

## 2. Completed Integrations

### Backend
1. **Dynamic Model Config Overrides:**
   - Updated [router.py](file:///Users/Jack/Desktop/projects/roundtabllm/backend/llm/router.py) to accept `model_overrides` and `forced_dissent`.
   - Implemented `_apply_overrides(models, overrides)` helper which deep-updates [ModelConfig](file:///Users/Jack/Desktop/projects/roundtabllm/backend/config.py) dataclasses at runtime.
   - Cleanly passed configurations to fallbacks inside `run_blind` and `run_debate` protocols.
2. **Claude Thinking Capture:**
   - Refactored `call_stream` in [claude.py](file:///Users/Jack/Desktop/projects/roundtabllm/backend/llm/claude.py) to yield structured dictionaries (`{"type": "text", "text": ...}` and `{"type": "thinking", "text": ...}`) rather than raw text strings.
   - Integrated `_read_stream` in [router.py](file:///Users/Jack/Desktop/projects/roundtabllm/backend/llm/router.py) to parse structured streams uniformly across Claude and Gemini.
3. **Error Formatting & Test Suite:**
   - Restored `_format_provider_error` exception formatter at the bottom of [router.py](file:///Users/Jack/Desktop/projects/roundtabllm/backend/llm/router.py).
   - Structured raw API exceptions (rate limits, content filters, unknown errors) into a unified `error_details` block sent over SSE.
   - Verified that the backend tests inside [test_roundtabllm.py](file:///Users/Jack/Desktop/projects/roundtabllm/backend/test_roundtabllm.py) pass cleanly.
4. **User Message Duplication Fix:**
   - Added logic to `run_round`, `run_blind`, and `run_debate` in [router.py](file:///Users/Jack/Desktop/projects/roundtabllm/backend/llm/router.py) to check if the last message in conversation history is already the user's current message before appending it. This resolves the duplicate context bug where models saw Jack's prompt twice.

### Frontend
1. **SSE Hook Subscription:**
   - Subscribed to `onThinkingToken` inside `useSSE` hook within [App.jsx](file:///Users/Jack/Desktop/projects/roundtabllm/frontend/src/App.jsx).
   - Accurately appends streamed tokens into the corresponding message's `thinking_content` property in real-time.
2. **React Callback Dependency Bugfix:**
   - Appended `modelOverrides` and `forcedDissent` into the React `useCallback` dependency lists for `handleSend` and `handleRegenerate` in [App.jsx](file:///Users/Jack/Desktop/projects/roundtabllm/frontend/src/App.jsx).
   - Prevents the chat runner from sending stale overrides/configurations after modifications are made in the settings panel.
3. **UI Enhancements:**
   - Changed `MessageBubble.jsx`'s default state of `showThinking` to `true` so reasoning blocks are expanded by default when they arrive.

---

## 3. Dev Setup & Verification Commands

To run the application locally or verify changes, use the following commands:

* **Backend Dev Server:**
  ```bash
  cd backend
  .venv/bin/uvicorn main:app --reload --port 8000
  ```
* **Frontend Dev Server:**
  ```bash
  cd frontend
  npm run dev
  ```
* **Production Rebuild:**
  ```bash
  cd frontend
  npm run build
  ```
  *(This builds the static files into `backend/static/` which are served by FastAPI in production.)*
* **Backend Unit Tests:**
  ```bash
  python -m unittest backend/test_roundtabllm.py
  ```

---

## 4. SQLite Concurrency Setup (WAL Mode)

The SQLite concurrency locking issues have been resolved by configuring the engine in [database.py](file:///Users/Jack/Desktop/projects/roundtabllm/backend/database.py#L8-L18):
1. **Thread checks disabled:** `check_same_thread: False` is passed to the connection arguments.
2. **Write-Ahead Logging (WAL) Mode:** Enabled via SQLAlchemy connection listener `PRAGMA journal_mode=WAL`.
3. **Synchronous Mode NORMAL:** Configured via `PRAGMA synchronous=NORMAL` for write-heavy SQLite operations.

---

## 5. Recommended Next Steps

1. **Verify Claude Thinking in a High-Complexity Prompt:**
   - Because simple queries may skip extended thinking or return only signature verification blocks, test Claude Opus 4.7 using a complex math, code, or logic puzzle to verify raw `thinking_delta` streaming.
2. **UI Settings Optimization:**
   - Display a status/info tool-tip next to the locked configurations (like GPT/Grok temperatures) indicating *why* they are locked (API architectural rules).
3. **Duplicate User Message Bug (Bug 2):**
   - **Status:** Resolved.
   - **Details:** The `run_round`, `run_blind`, and `run_debate` functions in `backend/llm/router.py` now check if the last message in history is already the current user message before appending, preventing prompt duplication.

