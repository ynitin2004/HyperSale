"""Eval tables (D37): gold-set items imported from fixtures, and per-rater labels."""
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EvalItem(Base):
    __tablename__ = "eval_items"
    __table_args__ = (UniqueConstraint("workspace_id", "item_key", name="uq_eval_items_key"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    item_key: Mapped[str] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(20))
    scenario_slug: Mapped[str] = mapped_column(String(80))
    applicable_criteria: Mapped[list] = mapped_column(JSONB)
    turns: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvalLabel(Base):
    __tablename__ = "eval_labels"
    __table_args__ = (
        UniqueConstraint("item_id", "rater_user_id", "criterion_id", name="uq_eval_labels_rater"),
        CheckConstraint("outcome IN ('1', '2', '3', '4', '5', 'insufficient_evidence')",
                        name="ck_eval_labels_outcome"),
        Index("ix_eval_labels_rater", "rater_user_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    item_id: Mapped[UUID] = mapped_column(ForeignKey("eval_items.id", ondelete="CASCADE"))
    rater_user_id: Mapped[UUID] = mapped_column()
    criterion_id: Mapped[str] = mapped_column(String(60))
    outcome: Mapped[str] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
