"""Database configuration, model and persistence operations."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings


# ``check_same_thread`` is a SQLite-only connect argument. For any other
# backend (e.g. PostgreSQL in production) it must be omitted. ``pool_pre_ping``
# recycles dropped connections, which matters when the database lives in a
# separate pod/service.
_is_sqlite = settings.DATABASE_URL.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _is_sqlite else {}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()


class Translation(Base):
    """Translation stored in the local history."""

    __tablename__ = "translations"

    id = Column(Integer, primary_key=True, index=True)

    direction = Column(String, nullable=False)
    input_text = Column(Text, nullable=False)
    output_text = Column(Text, nullable=False)

    status = Column(String, default="success")
    error_message = Column(Text)
    model = Column(String)

    repair_enabled = Column(Boolean, default=False)
    repair_applied = Column(Boolean, default=False)
    repair_changes = Column(Text)
    original_policy_before_repair = Column(Text)

    repair_attempts = Column(Integer, default=0, nullable=False)
    repair_stopped_reason = Column(Text)

    llm_calls = Column(Integer, default=0, nullable=False)
    duration_seconds = Column(Float, default=0.0, nullable=False)

    validation_report = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)


def _add_missing_columns() -> None:
    """Adds monitoring columns to an existing SQLite database."""

    inspector = inspect(engine)
    if "translations" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("translations")}

    columns = {
        "repair_attempts": "INTEGER NOT NULL DEFAULT 0",
        "repair_stopped_reason": "TEXT",
        "llm_calls": "INTEGER NOT NULL DEFAULT 0",
        "duration_seconds": "REAL NOT NULL DEFAULT 0.0",
    }

    with engine.begin() as connection:
        for name, definition in columns.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE translations ADD COLUMN {name} {definition}"))


def init_db() -> None:
    """Creates the database and updates existing local tables."""

    Base.metadata.create_all(bind=engine)
    _add_missing_columns()


def save_translation(
    direction: str,
    input_text: str,
    output_text: str,
    status: str = "success",
    error_message: str | None = None,
    model: str | None = None,
    repair_enabled: bool = False,
    repair_applied: bool = False,
    repair_changes: str | None = None,
    original_policy_before_repair: str | None = None,
    repair_attempts: int = 0,
    repair_stopped_reason: str | None = None,
    llm_calls: int = 0,
    duration_seconds: float = 0.0,
    validation_report: str | None = None,
) -> Translation:
    """Stores one translation."""

    db = SessionLocal()
    try:
        item = Translation(
            direction=direction,
            input_text=input_text,
            output_text=output_text,
            status=status,
            error_message=error_message,
            model=model,
            repair_enabled=repair_enabled,
            repair_applied=repair_applied,
            repair_changes=repair_changes,
            original_policy_before_repair=original_policy_before_repair,
            repair_attempts=repair_attempts,
            repair_stopped_reason=repair_stopped_reason,
            llm_calls=llm_calls,
            duration_seconds=duration_seconds,
            validation_report=validation_report,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item
    finally:
        db.close()


def get_recent_translations(limit: int = 10) -> list[Translation]:
    """Returns the most recent translations."""

    db = SessionLocal()
    try:
        return db.query(Translation).order_by(Translation.created_at.desc()).limit(limit).all()
    finally:
        db.close()


def delete_all_translations() -> int:
    """Deletes the complete translation history."""

    db = SessionLocal()
    try:
        deleted = db.query(Translation).delete()
        db.commit()
        return deleted
    finally:
        db.close()
