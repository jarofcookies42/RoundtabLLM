# RoundtabLLM

Multi-model AI deliberation engine — four LLMs in a structured roundtable with configurable protocols, modes, and anchoring.

## What It Does

You send a message. Four AI models respond in sequence, each seeing what the others said before it. The last model (the "anchor") sees everything and synthesizes. A memory-as-hint system loads only relevant context per round, AutoDream consolidation keeps memory current, and a compaction pipeline keeps long conversations affordable.

The result: richer, more nuanced answers than any single model produces alone.

## Models

| Slot | Regular Mode | Overdrive Mode |
|------|-------------|----------------|
| Claude | Sonnet 4.6 (thinking: enabled) | Opus 4.6 (thinking: adaptive) |
| GPT | 5.4 (no reasoning) | 5.4 (high reasoning) |
| Gemini | 3.1 Pro (low think) | 3.1 Pro (Deep Think Mini) |
| Grok | 4.20 non-reasoning | 4.20 reasoning |

## Two Modes

- **Regular** (~$0.02/round) — Fast, cheap, good for casual questions
- **Maximum Overdrive** (~$0.15-0.40/round) — All models at maximum reasoning depth

## Two Anchors

- **Knowledge anchor** — Claude goes last. Best for professional work, coding, analysis.
- **Abstract anchor** — Gemini goes last. Best for abstract reasoning, novel logic, scientific synthesis.

## Three Protocols

- **Roundtable** — Sequential round-robin. Each model builds on previous responses.
- **Blind -> Synthesis** — All models answer independently in parallel, then the anchor synthesizes.
- **Debate** — Two proposers (blind), one anonymized critic, one arbiter. Structured deliberation with role assignment UI.

## Quick Start

### Backend

```bash
cd backend
pip install -r requirements.txt
cd ..
uvicorn backend.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:3000** and enter your auth token.

## Environment Variables

Create a `.env` in the project root (see `.env.example`):

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_AI_API_KEY=AIza...
GROK_API_KEY=xai-...
AUTH_TOKEN=your-secret-token
```

## Deploy to Railway

```bash
# Build frontend
cd frontend && npm run build && cd ..

# Install Railway CLI and deploy
npm install -g @railway/cli
railway login
railway init --name roundtabllm
railway up --no-gitignore --detach
railway domain
railway variables set \
  ANTHROPIC_API_KEY="..." \
  OPENAI_API_KEY="..." \
  GOOGLE_AI_API_KEY="..." \
  GROK_API_KEY="..." \
  AUTH_TOKEN="..."
```

## Tech Stack

- **Backend:** FastAPI, SQLite (SQLModel), SSE streaming
- **Frontend:** React + Vite
- **Deploy:** Railway (Nixpacks)

## Documentation

See [CLAUDE.md](CLAUDE.md) for detailed technical documentation — API details, architecture, message formatting, protocol implementations, and configuration reference.

## Built With

Built entirely by [Claude Code](https://claude.ai). Powered by Claude Sonnet/Opus 4.6, GPT-5.4, Gemini 3.1 Pro, and Grok 4.20.
