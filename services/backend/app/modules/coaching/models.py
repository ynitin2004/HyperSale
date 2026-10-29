"""Assignments (D39). Completion is derived on read from practice sessions and reports."""
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Assignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (Index("ix_assignments_workspace_assignee", "workspace_id", "assignee_user_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    scenario_id: Mapped[UUID] = mapped_column(ForeignKey("scenarios.id"))
    assignee_user_id: Mapped[UUID] = mapped_column()
    assigned_by: Mapped[UUID] = mapped_column()
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
