"""
RoundtabLLM — FastAPI backend.

Routes:
  POST   /chat                  — send a message, returns conversation_id
  GET    /chat/stream/{conv_id} — SSE stream of model responses
  GET    /conversations         — list conversations
  GET    /conversations/{id}    — get full conversation with messages
  GET    /context               — get current shared context document
  POST   /context               — update shared context document
  POST   /import/{platform}     — upload a chat export (chatgpt, gemini, claude)
"""
import os
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import StreamingResponse, Response, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlmodel import Session, select
from contextlib import asynccontextmanager

from .database import init_db, get_session
from .models import Conversation, Message, ContextDoc, RawImport
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
    allow_origins=["*"],  # Tighten for production
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
    mode: str = "regular"               # "regular" or "overdrive"
    anchor: str = "knowledge"           # "knowledge" or "abstract"
    protocol: str = "roundtable"        # "roundtable", "blind", or "debate"
    enabled_models: list[str] = ["claude", "gpt", "gemini", "grok"]
    debate_roles: dict[str, str] | None = None  # {"claude": "proposer", "gpt": "critic", ...}


class ContextUpdateRequest(BaseModel):
    content: str


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
    )
    session.add(user_msg)
    session.commit()
    
    # Store round config on conversation
    conv.mode = req.mode
    conv.anchor = req.anchor
    conv.protocol = req.protocol
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

    # Parse debate_roles from JSON query param if provided
    import json as _json
    parsed_debate_roles = None
    if debate_roles:
        try:
            parsed_debate_roles = _json.loads(debate_roles)
        except _json.JSONDecodeError:
            pass

    # Dispatch to the correct protocol router
    async def event_stream():
        if protocol == "debate":
            async for event in run_debate(
                conversation_id=conversation_id,
                user_message=user_msg.content,
                mode=mode,
                anchor=anchor,
                enabled_models=model_list,
                context_content=context_content,
                session=session,
                debate_roles=parsed_debate_roles,
            ):
                yield event
        elif protocol == "blind":
            async for event in run_blind(
                conversation_id=conversation_id,
                user_message=user_msg.content,
                mode=mode,
                anchor=anchor,
                enabled_models=model_list,
                context_content=context_content,
                session=session,
            ):
                yield event
        else:
            async for event in run_round(
                conversation_id=conversation_id,
                user_message=user_msg.content,
                mode=mode,
                anchor=anchor,
                enabled_models=model_list,
                context_content=context_content,
                session=session,
            ):
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
    
    # TODO: Include thinking_content in response for chain-of-thought visualization UI
    return {
        "conversation": conv,
        "messages": [
            {"id": m.id, "role": m.role, "model": m.model, "name": m.name,
             "content": m.content, "is_error": m.is_error}
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

    # Build markdown
    from datetime import datetime as _dt
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

    for msg in messages:
        if msg.model == "user":
            lines.append(f"## 🗣 Jack")
        else:
            role_tag = f" `{msg.protocol_role}`" if msg.protocol_role else ""
            lines.append(f"## {msg.name}{role_tag}")

        lines.append("")
        lines.append(msg.content)
        lines.append("")

        # Collapsed thinking section
        if msg.thinking_content:
            lines.append("<details>")
            lines.append(f"<summary>💭 {msg.name} thinking</summary>")
            lines.append("")
            lines.append(msg.thinking_content)
            lines.append("")
            lines.append("</details>")
            lines.append("")

        lines.append("---")
        lines.append("")

    # Disagreement analysis placeholder
    lines.append("## Disagreement Analysis")
    lines.append("")
    lines.append("_TODO: Auto-generated disagreement analysis coming in a future update._")
    lines.append("")

    md = "\n".join(lines)
    filename = f"roundtabllm-{conversation_id}-{date_str}.md"

    return Response(
        content=md,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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

    # Save raw import for reprocessing
    raw_import = RawImport(
        platform=platform,
        filename=file.filename or "unknown",
        raw_json=raw_text,
    )
    session.add(raw_import)
    session.commit()

    # Parse based on platform
    parsers = {
        "chatgpt": parse_chatgpt_export,
        "claude": parse_claude_export,
    }

    if platform == "gemini":
        # Gemini needs a directory path, but for now handle raw HTML upload
        # The HTML content can be parsed directly
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
# Vite builds to backend/static/. Serve assets and fall back to index.html for SPA routing.

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
