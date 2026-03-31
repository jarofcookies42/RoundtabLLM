"""Database models for conversations, messages, and context."""
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class Conversation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = "New conversation"
    mode: str = "regular"           # "regular" or "overdrive"
    anchor: str = "knowledge"       # "knowledge" or "abstract"
    protocol: str = "roundtable"    # "roundtable", "blind", or "debate"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Message(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="conversation.id")
    role: str               # "user" or "assistant"
    model: str              # "user", "claude", "gpt", "gemini", "grok"
    name: str               # display name: "Jack", "Claude Sonnet 4.6", etc.
    content: str
    thinking_content: Optional[str] = Field(default=None)  # internal reasoning/thinking from model (Claude, Gemini)
    protocol_role: Optional[str] = Field(default=None)     # "proposal", "critic", "synthesis", or None (normal/roundtable)
    is_error: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ContextDoc(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    version: int = 1
    content: str
    source: str = "manual"  # "manual", "import_chatgpt", "import_gemini", "import_claude", "distilled"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RawImport(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    platform: str           # "chatgpt", "gemini", "claude"
    filename: str
    raw_json: str           # store the raw JSON for reprocessing
    imported_at: datetime = Field(default_factory=datetime.utcnow)
