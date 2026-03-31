# RoundtabLLM

Multi-model AI deliberation engine — four LLMs in a structured roundtable with configurable protocols, modes, and anchoring.

## What It Does

Send a message, and 2-4 AI models respond in sequence. Each model sees the full conversation including other models' responses, creating a genuine multi-perspective deliberation. A shared context document keeps all models aware of your background and preferences.

**Four models:** Claude (Anthropic), GPT-5.4 (OpenAI), Gemini 3.1 Pro (Google), Grok (xAI)

## Modes

| Mode | Cost | Config |
|------|------|--------|
| **Regular** | ~$0.02/round | Sonnet 4.6, GPT-5.4 (no reasoning), Gemini (low think), Grok (fast) |
| **Maximum Overdrive** | ~$0.15-0.40/round | Opus 4.6 (adaptive thinking), GPT-5.4 (high reasoning), Gemini (Deep Think Mini), Grok (reasoning) |

## Anchor Modes

Controls which model responds last, giving it the richest context:

- **Knowledge anchor** — Claude last. Best for professional work, coding, nuanced analysis.
- **Abstract anchor** — Gemini last. Best for abstract reasoning, novel logic, scientific synthesis.

## Protocols

- **Roundtable** — Sequential round-robin. Each model sees all previous responses.
- **Blind -> Synthesis** — All models answer independently in parallel. The anchor then synthesizes all responses.
- **Debate** — Two proposers answer blind. A critic evaluates anonymized proposals. An arbiter synthesizes with full attribution restored. Roles are user-assignable.

## Quick Start

```bash
# Clone and setup
git clone <repo-url> roundtabllm
cd roundtabllm
cp .env.example .env
# Fill in your API keys in .env

# Backend
cd backend
pip install -r requirements.txt
cd ..
uvicorn backend.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Open http://localhost:3000 and enter your auth token.

## Environment Variables

Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_AI_API_KEY=AIza...
GROK_API_KEY=xai-...
AUTH_TOKEN=your-secret-token
```

## Tech Stack

- **Backend:** Python, FastAPI, SQLite (SQLModel), SSE streaming
- **Frontend:** React, Vite, vanilla CSS-in-JS
- **LLM SDKs:** Anthropic, OpenAI, Google GenAI, xAI (OpenAI-compatible)

## Deploy to Railway

```bash
railway up
```

Set all environment variables in the Railway dashboard. The app serves the frontend as static files from the backend.

## Features

- Real-time SSE streaming with per-model typing indicators
- Thinking/reasoning capture (Claude thinking blocks stored and exportable)
- Session export to markdown with metadata, messages, and collapsed thinking sections
- File attachment via drag-and-drop (supports .md, .txt, .py, .json, .pdf, and more)
- Shared context/memory document editable in-app
- Chat history import from ChatGPT, Gemini, and Claude exports
- Model enable/disable toggles with per-model config display
- Debate role assignment with constraint enforcement

## Documentation

See [CLAUDE.md](CLAUDE.md) for detailed technical documentation including API details, architecture decisions, message formatting rules, and temperature constraints.

## Built With

[Claude](https://anthropic.com) | [GPT-5.4](https://openai.com) | [Gemini 3.1 Pro](https://deepmind.google) | [Grok](https://x.ai)
