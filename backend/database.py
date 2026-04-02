"""SQLite database setup and initialization."""
import os
from sqlmodel import SQLModel, Session, create_engine, select
from .config import DATABASE_URL
from .models import ContextDoc, MemoryFile

engine = create_engine(DATABASE_URL, echo=False)


def _migrate(engine):
    """Run lightweight migrations for schema changes."""
    import sqlalchemy
    with engine.connect() as conn:
        # Message table migrations
        result = conn.execute(sqlalchemy.text("PRAGMA table_info(message)"))
        msg_columns = {row[1] for row in result}
        if "thinking_content" not in msg_columns:
            conn.execute(sqlalchemy.text("ALTER TABLE message ADD COLUMN thinking_content TEXT"))
        if "protocol_role" not in msg_columns:
            conn.execute(sqlalchemy.text("ALTER TABLE message ADD COLUMN protocol_role TEXT"))
        if "source" not in msg_columns:
            conn.execute(sqlalchemy.text("ALTER TABLE message ADD COLUMN source TEXT DEFAULT 'user'"))
        if "trust_tier" not in msg_columns:
            conn.execute(sqlalchemy.text("ALTER TABLE message ADD COLUMN trust_tier TEXT DEFAULT 'direct'"))
        if "compacted" not in msg_columns:
            conn.execute(sqlalchemy.text("ALTER TABLE message ADD COLUMN compacted BOOLEAN DEFAULT 0"))

        # MemoryFile table migrations
        result = conn.execute(sqlalchemy.text("PRAGMA table_info(memoryfile)"))
        mem_columns = {row[1] for row in result}
        if "source" not in mem_columns:
            conn.execute(sqlalchemy.text("ALTER TABLE memoryfile ADD COLUMN source TEXT DEFAULT 'seed'"))
        if "last_modified_by" not in mem_columns:
            conn.execute(sqlalchemy.text("ALTER TABLE memoryfile ADD COLUMN last_modified_by TEXT DEFAULT 'user'"))
        if "derived_from" not in mem_columns:
            conn.execute(sqlalchemy.text("ALTER TABLE memoryfile ADD COLUMN derived_from TEXT"))

        # Conversation table migrations
        result = conn.execute(sqlalchemy.text("PRAGMA table_info(conversation)"))
        conv_columns = {row[1] for row in result}
        if "protocol" not in conv_columns:
            conn.execute(sqlalchemy.text("ALTER TABLE conversation ADD COLUMN protocol TEXT DEFAULT 'roundtable'"))
        if "context_mode" not in conv_columns:
            conn.execute(sqlalchemy.text("ALTER TABLE conversation ADD COLUMN context_mode TEXT DEFAULT 'full'"))
        if "selected_topics" not in conv_columns:
            conn.execute(sqlalchemy.text("ALTER TABLE conversation ADD COLUMN selected_topics TEXT"))

        conn.commit()


def _seed_memory(session: Session):
    """Seed memory files from backend/memory/ directory if DB is empty."""
    existing = session.exec(select(MemoryFile)).first()
    if existing:
        return  # Already seeded

    memory_dir = os.path.join(os.path.dirname(__file__), "memory")
    if not os.path.isdir(memory_dir):
        return

    # Seed index
    index_path = os.path.join(memory_dir, "memory_index.md")
    if os.path.exists(index_path):
        with open(index_path, "r") as f:
            session.add(MemoryFile(key="index", content=f.read(), file_type="index"))

    # Seed topic files
    topic_keys = ["identity", "thesis", "projects", "health", "family", "tech", "work_style"]
    for key in topic_keys:
        path = os.path.join(memory_dir, f"{key}.md")
        if os.path.exists(path):
            with open(path, "r") as f:
                session.add(MemoryFile(key=key, content=f.read(), file_type="topic"))

    session.commit()


def init_db():
    """Create tables, run migrations, and seed context/memory if empty."""
    SQLModel.metadata.create_all(engine)
    _migrate(engine)

    with Session(engine) as session:
        # Seed legacy context doc
        existing = session.exec(select(ContextDoc)).first()
        if not existing:
            seed_path = os.path.join(os.path.dirname(__file__), "..", "context", "jack_context.md")
            if os.path.exists(seed_path):
                with open(seed_path, "r") as f:
                    content = f.read()
                session.add(ContextDoc(content=content, source="seed"))
                session.commit()

        # Seed memory files
        _seed_memory(session)


def get_session():
    with Session(engine) as session:
        yield session
