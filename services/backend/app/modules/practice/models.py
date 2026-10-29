"""Practice tables: one row per roleplay and its server-authoritative transcript (D29)."""
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PracticeSession(Base):
    __tablename__ = "practice_sessions"
    __table_args__ = (
        Index("ix_practice_sessions_workspace_created", "workspace_id", "created_at"),
        Index("ix_practice_sessions_status", "status"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    user_id: Mapped[UUID] = mapped_column()
    scenario_id: Mapped[UUID] = mapped_column(ForeignKey("scenarios.id"))
    persona_id: Mapped[UUID] = mapped_column(ForeignKey("personas.id"))
    prompt_version: Mapped[str] = mapped_column(String(32))
    rubric_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="created")
    provider: Mapped[str] = mapped_column(String(40))
    model_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    session_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cap_seconds: Mapped[int] = mapped_column(Integer)
    end_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recorder_offset_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recording_chunks: Mapped[int] = mapped_column(Integer, default=0)
    recording_bytes: Mapped[int] = mapped_column(Integer, default=0)
    recording_mime: Mapped[str | None] = mapped_column(String(80), nullable=True)
    timings: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TranscriptTurn(Base):
    __tablename__ = "transcript_turns"
    __table_args__ = (
        UniqueConstraint("session_id", "item_id", name="uq_transcript_turns_item"),
        Index("ix_transcript_turns_session", "session_id", "start_ms"),
        CheckConstraint("speaker IN ('rep', 'buyer')", name="ck_transcript_turns_speaker"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    session_id: Mapped[UUID] = mapped_column(ForeignKey("practice_sessions.id", ondelete="CASCADE"))
    idx: Mapped[int] = mapped_column(Integer)
    speaker: Mapped[str] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(Text)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
