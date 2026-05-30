"""Database models for conversations, messages, context, and memory."""
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class Conversation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = "New conversation"
    mode: str = "regular"           # "regular" or "overdrive"
    anchor: str = "knowledge"       # "knowledge" or "abstract"
    protocol: str = "roundtable"    # "roundtable", "blind", or "debate"
    context_mode: str = "full"      # "full", "select", or "none"
    selected_topics: Optional[str] = Field(default=None)  # JSON list: '["thesis","projects"]' or null
    forced_dissent: bool = Field(default=False)
    archived: bool = Field(default=False)
    config: Optional[str] = Field(default=None)  # JSON-serialized: SessionConfig
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
    source: str = "user"            # "user", "claude", "gpt", "gemini", "grok", "system", "autodream", "import_*"
    trust_tier: str = "direct"      # "direct", "model", "derived", "imported", "system"
    compacted: bool = False         # True = summarized and excluded from model context
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ContextDoc(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    version: int = 1
    content: str
    source: str = "manual"  # "manual", "import_chatgpt", "import_gemini", "import_claude", "distilled"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MemoryFile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(index=True, unique=True)  # "index", "identity", "thesis", etc.
    content: str
    file_type: str = "topic"        # "index" or "topic"
    source: str = "seed"            # "seed", "manual", "autodream", "import"
    last_modified_by: str = "user"  # "user", "autodream", "import_distiller"
    derived_from: Optional[str] = Field(default=None)  # JSON: {"dream_id": 5, "conversations": [12,13]} or null
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DreamLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    status: str = "pending"         # "pending", "approved", "partially_approved", "rejected", "failed"
    proposed_changes: Optional[str] = Field(default=None)   # JSON: full diff from dream call
    applied_changes: Optional[str] = Field(default=None)    # JSON: what user approved (null until reviewed)
    conversations_processed: Optional[str] = Field(default=None)  # JSON: list of conversation IDs scanned
    summary: Optional[str] = Field(default=None)
    token_cost: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RawImport(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    platform: str           # "chatgpt", "gemini", "claude"
    filename: str
    raw_json: str           # store the raw JSON for reprocessing
    imported_at: datetime = Field(default_factory=datetime.utcnow)


class ModelOutcome(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="conversation.id")
    model: str              # e.g., "claude", "gpt"
    position_in_synthesis: float = 0.0  # 0.0 to 1.0 representing how much of their proposal survived
    dissent_count: int = 0
    user_accepted: Optional[bool] = Field(default=None)
    category: str           # task category e.g. "coding_agentic"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ModelScoreInternal(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    model: str = Field(index=True)
    category: str = Field(index=True)
    rolling_average: float = 0.5
    sample_count: int = 0
    updated_at: datetime = Field(default_factory=datetime.utcnow)

