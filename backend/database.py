"""SQLite database setup and initialization."""
import os
from sqlmodel import SQLModel, Session, create_engine, select
from .config import DATABASE_URL
from .models import ContextDoc

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

        # Conversation table migrations
        result = conn.execute(sqlalchemy.text("PRAGMA table_info(conversation)"))
        conv_columns = {row[1] for row in result}
        if "protocol" not in conv_columns:
            conn.execute(sqlalchemy.text("ALTER TABLE conversation ADD COLUMN protocol TEXT DEFAULT 'roundtable'"))

        conn.commit()


def init_db():
    """Create tables, run migrations, and seed context if empty."""
    SQLModel.metadata.create_all(engine)
    _migrate(engine)

    with Session(engine) as session:
        existing = session.exec(select(ContextDoc)).first()
        if not existing:
            seed_path = os.path.join(os.path.dirname(__file__), "..", "context", "jack_context.md")
            if os.path.exists(seed_path):
                with open(seed_path, "r") as f:
                    content = f.read()
                session.add(ContextDoc(content=content, source="seed"))
                session.commit()


def get_session():
    with Session(engine) as session:
        yield session
