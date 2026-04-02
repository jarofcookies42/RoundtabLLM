"""
RoundtabLLM — FastAPI backend.

Routes:
  POST   /chat                  — send a message, returns conversation_id
  GET    /chat/stream/{conv_id} — SSE stream of model responses
  GET    /conversations         — list conversations
  GET    /conversations/{id}    — get full conversation with messages
  GET    /context               — get current shared context document (legacy)
  POST   /context               — update shared context document (legacy)
  GET    /memory                — get memory index + all topic files
  GET    /memory/{key}          — get one topic file
  PUT    /memory/{key}          — update one topic file
  POST   /memory/dream          — trigger AutoDream consolidation pass
  GET    /memory/dream/{id}     — get a specific dream log
  GET    /memory/dreams         — list all dream logs
  POST   /memory/dream/{id}/apply  — apply approved dream changes
  POST   /memory/dream/{id}/reject — reject all dream changes
  POST   /import/{platform}     — upload a chat export (chatgpt, gemini, claude)
"""
import os
import json as _json
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import StreamingResponse, Response, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlmodel import Session, select
from contextlib import asynccontextmanager

from .database import init_db, get_session
from .models import Conversation, Message, ContextDoc, RawImport, MemoryFile, DreamLog
from .memory.autodream import generate_dream, apply_dream_changes
from .memory.compaction import compact_conversation
from .config import AUTH_TOKEN
from .llm.router import run_round, run_blind, run_debate
from .context import get_current_context, update_context
from .importers.chatgpt import parse_chatgpt_export
from .importers.gemini import parse_gemini_export
from .importers.claude_export import parse_claude_export


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="RoundtabLLM", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Auth (simple bearer token) ---

def verify_auth(request: Request):
    """Simple auth check. Pass token as Bearer header or ?token= query param."""
    auth = request.headers.get("Authorization", "")
    token = request.query_params.get("token", "")
    if auth == f"Bearer {AUTH_TOKEN}" or token == AUTH_TOKEN:
        return True
    raise HTTPException(status_code=401, detail="Unauthorized")


# --- Request/Response Models ---

class ChatRequest(BaseModel):
    message: str
    conversation_id: int | None = None
    mode: str = "regular"
    anchor: str = "knowledge"
    protocol: str = "roundtable"
    enabled_models: list[str] = ["claude", "gpt", "gemini", "grok"]
    debate_roles: dict[str, str] | None = None
    context_mode: str = "full"                       # "full", "select", or "none"
    selected_topics: list[str] | None = None         # ["thesis", "projects"] for select mode


class ContextUpdateRequest(BaseModel):
    content: str


class MemoryUpdateRequest(BaseModel):
    content: str


class DreamRequest(BaseModel):
    conversation_ids: list[int] | None = None


class DreamApplyRequest(BaseModel):
    approved_indices: list[int]


class CompactRequest(BaseModel):
    keep_recent: int = 6


# --- Routes ---

@app.post("/chat")
async def send_chat(
    req: ChatRequest,
    session: Session = Depends(get_session),
    _auth = Depends(verify_auth),
):
    """Create or continue a conversation. Returns conversation_id for SSE streaming."""
    if req.conversation_id:
        conv = session.get(Conversation, req.conversation_id)
        if not conv:
            raise HTTPException(404, "Conversation not found")
    else:
        conv = Conversation(mode=req.mode, anchor=req.anchor, protocol=req.protocol)
        session.add(conv)
        session.commit()
        session.refresh(conv)

    # Save user message
    user_msg = Message(
        conversation_id=conv.id,
        role="user",
        model="user",
        name="Jack",
        content=req.message,
        source="user",
        trust_tier="direct",
    )
    session.add(user_msg)
    session.commit()

    # Store round config on conversation
    conv.mode = req.mode
    conv.anchor = req.anchor
    conv.protocol = req.protocol
    conv.context_mode = req.context_mode
    conv.selected_topics = _json.dumps(req.selected_topics) if req.selected_topics else None
    session.add(conv)
    session.commit()

    return {
        "conversation_id": conv.id,
        "mode": req.mode,
        "anchor": req.anchor,
        "protocol": req.protocol,
    }


@app.get("/chat/stream/{conversation_id}")
async def stream_chat(
    conversation_id: int,
    mode: str = "regular",
    anchor: str = "knowledge",
    protocol: str = "roundtable",
    enabled_models: str = "claude,gpt,gemini,grok",
    debate_roles: str | None = None,
    context_mode: str = "full",
    selected_topics: str | None = None,
    session: Session = Depends(get_session),
    _auth = Depends(verify_auth),
):
    """SSE stream of model responses for the latest user message in a conversation."""
    conv = session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")

    # Get latest user message
    messages = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())  # type: ignore
    ).all()

    user_msg = next((m for m in messages if m.role == "user"), None)
    if not user_msg:
        raise HTTPException(400, "No user message found")

    context_content = get_current_context(session)
    model_list = [m.strip() for m in enabled_models.split(",")]

    # Parse debate_roles and selected_topics from JSON query params
    parsed_debate_roles = None
    if debate_roles:
        try:
            parsed_debate_roles = _json.loads(debate_roles)
        except _json.JSONDecodeError:
            pass

    parsed_selected_topics = None
    if selected_topics:
        try:
            parsed_selected_topics = _json.loads(selected_topics)
        except _json.JSONDecodeError:
            pass

    # Dispatch to the correct protocol router
    async def event_stream():
        common_kwargs = dict(
            conversation_id=conversation_id,
            user_message=user_msg.content,
            mode=mode,
            anchor=anchor,
            enabled_models=model_list,
            context_content=context_content,
            session=session,
            context_mode=context_mode,
            selected_topics=parsed_selected_topics,
        )
        if protocol == "debate":
            async for event in run_debate(**common_kwargs, debate_roles=parsed_debate_roles):
                yield event
        elif protocol == "blind":
            async for event in run_blind(**common_kwargs):
                yield event
        else:
            async for event in run_round(**common_kwargs):
                yield event

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/conversations")
async def list_conversations(
    session: Session = Depends(get_session),
    _auth = Depends(verify_auth),
):
    convs = session.exec(
        select(Conversation).order_by(Conversation.updated_at.desc())  # type: ignore
    ).all()
    return [{"id": c.id, "title": c.title, "mode": c.mode, "updated_at": str(c.updated_at)} for c in convs]


@app.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: int,
    session: Session = Depends(get_session),
    _auth = Depends(verify_auth),
):
    conv = session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(404)

    messages = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)  # type: ignore
    ).all()

    return {
        "conversation": conv,
        "messages": [
            {"id": m.id, "role": m.role, "model": m.model, "name": m.name,
             "content": m.content, "is_error": m.is_error,
             "source": m.source, "trust_tier": m.trust_tier,
             "protocol_role": m.protocol_role}
            for m in messages
        ],
    }


@app.get("/conversations/{conversation_id}/export")
async def export_conversation(
    conversation_id: int,
    session: Session = Depends(get_session),
    _auth = Depends(verify_auth),
):
    """Export a conversation as a markdown file."""
    conv = session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(404)

    messages = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)  # type: ignore
    ).all()

    date_str = conv.created_at.strftime("%Y-%m-%d")
    lines = [
        f"# RoundtabLLM — Session {conversation_id}",
        "",
        "| Key | Value |",
        "| --- | --- |",
        f"| Date | {date_str} |",
        f"| Mode | {conv.mode} |",
        f"| Anchor | {conv.anchor} |",
        f"| Protocol | {conv.protocol} |",
        f"| Models | {', '.join(set(m.model for m in messages if m.model != 'user'))} |",
        "",
        "---",
        "",
    ]

    # Separate compacted messages from active ones
    compacted_msgs = [m for m in messages if m.compacted]
    active_msgs = [m for m in messages if not m.compacted]

    # Show compacted messages in a collapsed section if any exist
    if compacted_msgs:
        lines.append("## Compacted Messages (summarized in conversation)")
        lines.append("")
        # Show the compaction summary first
        summaries = [m for m in active_msgs if m.model == "compaction"]
        for s in summaries:
            lines.append(f"**{s.name}**")
            lines.append("")
            lines.append(s.content)
            lines.append("")

        lines.append("<details>")
        lines.append("<summary>Original compacted messages</summary>")
        lines.append("")
        for msg in compacted_msgs:
            name = "Jack" if msg.model == "user" else msg.name
            lines.append(f"**{name}:** {msg.content}")
            lines.append("")
        lines.append("</details>")
        lines.append("")
        lines.append("---")
        lines.append("")

    for msg in active_msgs:
        if msg.model == "compaction":
            continue  # Already shown above if compacted section exists
        if msg.model == "user":
            lines.append(f"## Jack")
        else:
            role_tag = f" `{msg.protocol_role}`" if msg.protocol_role else ""
            lines.append(f"## {msg.name}{role_tag}")

        if msg.trust_tier and msg.trust_tier not in ("direct", "model"):
            lines.append(f"*Source: {msg.source} | Trust: {msg.trust_tier}*")

        lines.append("")
        lines.append(msg.content)
        lines.append("")

        if msg.thinking_content:
            lines.append("<details>")
            lines.append(f"<summary>{msg.name} thinking</summary>")
            lines.append("")
            lines.append(msg.thinking_content)
            lines.append("")
            lines.append("</details>")
            lines.append("")

        lines.append("---")
        lines.append("")

    md = "\n".join(lines)
    filename = f"roundtabllm-{conversation_id}-{date_str}.md"

    return Response(
        content=md,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/conversations/{conversation_id}/compact")
async def compact_conv(
    conversation_id: int,
    req: CompactRequest = CompactRequest(),
    session: Session = Depends(get_session),
    _auth = Depends(verify_auth),
):
    """Manually trigger compaction on a conversation."""
    conv = session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    result = await compact_conversation(session, conversation_id, keep_recent=req.keep_recent)
    if result.get("error"):
        raise HTTPException(500, result["error"])
    return result


# --- Legacy context endpoints (backward compatibility) ---

@app.get("/context")
async def get_context(
    session: Session = Depends(get_session),
    _auth = Depends(verify_auth),
):
    content = get_current_context(session)
    return {"content": content}


@app.post("/context")
async def post_context(
    req: ContextUpdateRequest,
    session: Session = Depends(get_session),
    _auth = Depends(verify_auth),
):
    update_context(session, req.content)
    return {"status": "ok"}


# --- Memory endpoints ---

@app.get("/memory")
async def get_memory(
    session: Session = Depends(get_session),
    _auth = Depends(verify_auth),
):
    """Return memory index + all topic files."""
    files = session.exec(select(MemoryFile)).all()

    index_content = ""
    topics = {}
    topic_meta = {}
    for f in files:
        if f.file_type == "index":
            index_content = f.content
        else:
            topics[f.key] = f.content
            topic_meta[f.key] = {
                "source": f.source,
                "last_modified_by": f.last_modified_by,
                "derived_from": f.derived_from,
            }

    # Calculate memory stats
    total_chars = sum(len(c) for c in topics.values())
    total_lines = sum(c.count("\n") + 1 for c in topics.values())

    return {
        "index": index_content,
        "topics": topics,
        "topic_meta": topic_meta,
        "stats": {
            "chars": total_chars,
            "lines": total_lines,
            "topics": len(topics),
            "cap_chars": 25000,
            "cap_lines": 200,
        },
    }


# --- AutoDream endpoints ---

@app.post("/memory/dream")
async def trigger_dream(
    req: DreamRequest = DreamRequest(),
    session: Session = Depends(get_session),
    _auth = Depends(verify_auth),
):
    """Trigger an AutoDream consolidation pass."""
    # Check consolidation lock
    pending = session.exec(select(DreamLog).where(DreamLog.status == "pending")).first()
    if pending:
        raise HTTPException(409, "A dream is already in progress")

    result = await generate_dream(session, req.conversation_ids)
    if result.get("error") and "already in progress" in result["error"]:
        raise HTTPException(409, result["error"])
    return result


@app.get("/memory/dreams")
async def list_dreams(
    session: Session = Depends(get_session),
    _auth = Depends(verify_auth),
):
    """List all dream logs."""
    dreams = session.exec(
        select(DreamLog).order_by(DreamLog.created_at.desc())  # type: ignore
    ).all()
    return [
        {
            "id": d.id,
            "status": d.status,
            "summary": d.summary,
            "token_cost": d.token_cost,
            "created_at": str(d.created_at),
            "conversations_processed": _json.loads(d.conversations_processed) if d.conversations_processed else [],
        }
        for d in dreams
    ]


@app.get("/memory/dream/{dream_id}")
async def get_dream(
    dream_id: int,
    session: Session = Depends(get_session),
    _auth = Depends(verify_auth),
):
    """Get a specific dream log with proposed changes."""
    dream = session.get(DreamLog, dream_id)
    if not dream:
        raise HTTPException(404, "Dream not found")
    return {
        "id": dream.id,
        "status": dream.status,
        "summary": dream.summary,
        "proposed_changes": _json.loads(dream.proposed_changes) if dream.proposed_changes else None,
        "applied_changes": _json.loads(dream.applied_changes) if dream.applied_changes else None,
        "conversations_processed": _json.loads(dream.conversations_processed) if dream.conversations_processed else [],
        "token_cost": dream.token_cost,
        "created_at": str(dream.created_at),
    }


@app.post("/memory/dream/{dream_id}/apply")
async def apply_dream(
    dream_id: int,
    req: DreamApplyRequest,
    session: Session = Depends(get_session),
    _auth = Depends(verify_auth),
):
    """Apply user-approved changes from a dream pass."""
    result = apply_dream_changes(session, dream_id, req.approved_indices)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@app.post("/memory/dream/{dream_id}/reject")
async def reject_dream(
    dream_id: int,
    session: Session = Depends(get_session),
    _auth = Depends(verify_auth),
):
    """Reject all proposed changes from a dream pass."""
    dream = session.get(DreamLog, dream_id)
    if not dream:
        raise HTTPException(404, "Dream not found")
    if dream.status != "pending":
        raise HTTPException(400, f"Dream is already {dream.status}")
    dream.status = "rejected"
    dream.applied_changes = _json.dumps([])
    session.add(dream)
    session.commit()
    return {"status": "rejected"}


# --- Memory topic endpoints ---

@app.get("/memory/{key}")
async def get_memory_topic(
    key: str,
    session: Session = Depends(get_session),
    _auth = Depends(verify_auth),
):
    """Return one memory topic file."""
    mem = session.exec(select(MemoryFile).where(MemoryFile.key == key)).first()
    if not mem:
        raise HTTPException(404, f"Memory topic '{key}' not found")
    return {
        "key": mem.key, "content": mem.content, "file_type": mem.file_type,
        "source": mem.source, "last_modified_by": mem.last_modified_by,
        "derived_from": mem.derived_from,
    }


@app.put("/memory/{key}")
async def update_memory_topic(
    key: str,
    req: MemoryUpdateRequest,
    session: Session = Depends(get_session),
    _auth = Depends(verify_auth),
):
    """Update one memory topic file."""
    mem = session.exec(select(MemoryFile).where(MemoryFile.key == key)).first()
    if not mem:
        raise HTTPException(404, f"Memory topic '{key}' not found")
    mem.content = req.content
    mem.source = "manual"
    mem.last_modified_by = "user"
    mem.derived_from = None
    mem.updated_at = datetime.utcnow()
    session.add(mem)
    session.commit()
    return {"status": "ok"}


# --- Import endpoint ---

@app.post("/import/{platform}")
async def import_export(
    platform: str,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    _auth = Depends(verify_auth),
):
    """Import chat history from another platform. Supports: chatgpt, gemini, claude."""
    if platform not in ("chatgpt", "gemini", "claude"):
        raise HTTPException(400, f"Unsupported platform: {platform}")

    raw = await file.read()
    raw_text = raw.decode("utf-8")

    raw_import = RawImport(
        platform=platform,
        filename=file.filename or "unknown",
        raw_json=raw_text,
    )
    session.add(raw_import)
    session.commit()

    parsers = {
        "chatgpt": parse_chatgpt_export,
        "claude": parse_claude_export,
    }

    if platform == "gemini":
        from .importers.gemini import _parse_html_activities
        conversations = _parse_html_activities(raw_text)
    else:
        parser = parsers[platform]
        conversations = parser(raw_text)

    return {
        "platform": platform,
        "conversations_parsed": len(conversations),
        "total_messages": sum(len(c["messages"]) for c in conversations),
    }


# --- Static file serving (production) ---

_static_dir = Path(__file__).parent / "static"

if _static_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=_static_dir / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        """Serve static files or fall back to index.html for SPA routing."""
        file = _static_dir / path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(_static_dir / "index.html")
