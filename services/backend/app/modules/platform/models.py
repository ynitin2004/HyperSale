"""Platform tables (M4): per-workspace settings (D46, D47) and the append-only audit log (D47)."""
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

DEFAULT_AUDIO_RETENTION_DAYS = 90
DEFAULT_MONTHLY_LIMIT_MICROUSD = 10_000_000  # $10


class WorkspaceSettings(Base):
    """One row per workspace, created on first save. A missing row means the defaults."""

    __tablename__ = "workspace_settings"
    __table_args__ = (
        CheckConstraint("audio_retention_days IS NULL OR audio_retention_days BETWEEN 1 AND 3650",
                        name="ck_workspace_settings_retention"),
        CheckConstraint("monthly_limit_microusd IS NULL OR monthly_limit_microusd >= 0",
                        name="ck_workspace_settings_limit"),
    )
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    # NULL means "keep audio" / "no limit"; both are owner choices, not missing data.
    audio_retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True,
                                                             server_default=str(DEFAULT_AUDIO_RETENTION_DAYS))
    monthly_limit_microusd: Mapped[int | None] = mapped_column(BigInteger, nullable=True,
                                                               server_default=str(DEFAULT_MONTHLY_LIMIT_MICROUSD))
    record_roleplay_audio: Mapped[bool] = mapped_column(Boolean, server_default="true")
    updated_by: Mapped[UUID | None] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_workspace_created", "workspace_id", "created_at"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    # NULL actor means the system, e.g. the retention sweep.
    actor_user_id: Mapped[UUID | None] = mapped_column(nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
