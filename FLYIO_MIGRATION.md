# Fly.io Migration — Claude Code Prompt

**For Jack:** Open Claude Code in `/Users/Jack/Desktop/projects/roundtabllm`, then paste everything between `--- PROMPT START ---` and `--- PROMPT END ---` below.

**Time estimate:** 30-60 min if nothing goes sideways, 90-120 with debugging.
**Cost on Fly:** ~$2-5/month at this scale, often free under hobby plan.

---

## --- PROMPT START ---

You are migrating RoundtabLLM from Railway to Fly.io. The current Railway deployment is offline (trial expired around April 23, 2026). The app is FastAPI + React + SQLite, with the database on a persistent volume. We need the same architecture on Fly.io: containerized app, persistent volume mounted at `/data`, SQLite at `/data/roundtable.db`, env vars managed by Fly secrets. Postgres migration is explicitly deferred until pre-multi-user — do not attempt it here.

### Current state to preserve

- Entry point: `backend.main:app` (FastAPI), serves Vite-built static from `backend/static/`.
- Frontend builds with `cd frontend && npm install && npm run build`. Output lands in `backend/static/` per Vite config.
- DB path logic in `backend/config.py` already handles this — uses `/data/roundtable.db` if `/data/` exists, otherwise local. Don't change it. The Fly volume mount at `/data` makes it Just Work.
- Required env vars: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_AI_API_KEY`, `GROK_API_KEY`, `AUTH_TOKEN`. These go in as Fly secrets.

### Files to create

1. **`Dockerfile`** — multi-stage:
   - Stage 1 (node:20-alpine): build frontend, output to `backend/static/`
   - Stage 2 (python:3.11-slim): copy backend, `pip install -r requirements.txt`, copy built static from stage 1
   - CMD: `uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}`

2. **`fly.toml`**:
   - App name: try `roundtabllm` first; if taken use `roundtabllm-prod`
   - Primary region: `dfw` (Dallas — closest to Lubbock)
   - `[build]` referencing the Dockerfile
   - `[mounts]` section: `source = "roundtable_data"`, `destination = "/data"`
   - `[http_service]`: internal_port 8000, force_https = true, auto_stop_machines = false, min_machines_running = 1
   - VM size: `shared-cpu-1x`, 256MB to start (scale to 512 if it OOMs)

3. **`.dockerignore`** — at minimum: `.git`, `node_modules`, `frontend/node_modules`, `*.db`, `.env`, `.railwayignore`, `Procfile`, `railway.toml`, backups

### Migration steps

Run from project root. Install flyctl first if missing (`brew install flyctl`), then `flyctl auth login`.

1. `flyctl launch --no-deploy` — generates baseline. Edit `fly.toml` to match the spec above.
2. `flyctl volumes create roundtable_data --region dfw --size 1` — 1GB is the minimum, plenty of headroom.
3. Set secrets, pulling values from `.env` (ask Jack to confirm or read them):
   ```
   flyctl secrets set ANTHROPIC_API_KEY="..." OPENAI_API_KEY="..." GOOGLE_AI_API_KEY="..." GROK_API_KEY="..." AUTH_TOKEN="..."
   ```
4. `flyctl deploy` — first deploy. If it fails on health check, debug from `flyctl logs`.
5. **Restore the DB** — once the app is up but before declaring done:
   - Backup is at `/Users/Jack/Desktop/roundtabllm-backup-20260421.tar.gz` (71KB, contains `roundtable.db` only)
   - Extract: `cd /tmp && tar -xzf /Users/Jack/Desktop/roundtabllm-backup-20260421.tar.gz`
   - Push: `flyctl ssh sftp shell`, then `put /tmp/roundtable.db /data/roundtable.db`
   - Restart: `flyctl apps restart roundtabllm`
6. Verify the URL works (see verification list below).

### What NOT to do

- Don't delete `Procfile` or `railway.toml` yet. Leave them until Fly is verified stable. Cleanup commit later.
- Don't migrate to Postgres. SQLite on Fly volume handles current scale fine (~133 messages, 272KB DB).
- Don't change application code beyond the three new files. The `/data` autodetect in `config.py` is already correct.
- Don't run `flyctl launch` interactively past the `--no-deploy` step — it'll try to deploy before the volume exists.

### Documentation update (last step before declaring done)

1. **`CLAUDE.md`**:
   - Change "Deploy target: Railway" to "Deploy target: Fly.io"
   - Add a brief "Deployment History" section noting April→May 2026 Railway → Fly.io migration
   - Replace any Railway-specific paths or commands

2. **`README.md`**:
   - Replace the "Deploy to Railway" section with "Deploy to Fly.io" reflecting commands actually used
   - Update the live demo URL

3. Commit: `feat: migrate from Railway to Fly.io with persistent SQLite volume`. Push to GitHub.

### Verification checklist

- [ ] App reachable at Fly URL over HTTPS
- [ ] Auth works (bearer token rejects bad tokens, accepts good ones)
- [ ] Conversations from April 21 backup are visible in the UI
- [ ] New message in Regular mode succeeds (all 4 models respond)
- [ ] Container restart preserves DB (`flyctl apps restart` then confirm conversations still there)
- [ ] CLAUDE.md and README.md updated
- [ ] Changes committed and pushed

## --- PROMPT END ---

---

## After this is done

Next priority is Bug 2 (user message duplication). Fix location: `backend/llm/router.py`, `_load_conversation_history()` around line 541. The bug is that history loading runs after the new user message is saved AND the current turn gets passed separately, causing duplication. Fix: either load history before saving, or exclude the current turn when loading. Touches `backend/main.py` `/chat` endpoint and `backend/llm/router.py`. Small backend-only diff.

After Bug 2: Bug 1 (silent model failures) — bigger, touches App.jsx, router.py, and per-provider error extraction. Wait until Bug 2 ships so router.py is in a cleaner state for the surgery.
