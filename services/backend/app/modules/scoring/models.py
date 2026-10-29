"""Scoring tables: a report per session and one verified score per applicable criterion."""
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_reports_session"),
        Index("ix_reports_workspace_created", "workspace_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    session_id: Mapped[UUID] = mapped_column(ForeignKey("practice_sessions.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    rubric_version: Mapped[str] = mapped_column(String(40))
    prompt_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    metrics_version: Mapped[str] = mapped_column(String(20))
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    overall: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    drills: Mapped[list] = mapped_column(JSONB, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    timings: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CriterionScore(Base):
    __tablename__ = "criterion_scores"
    __table_args__ = (
        UniqueConstraint("report_id", "criterion_id", name="uq_criterion_scores_report_criterion"),
        Index("ix_criterion_scores_report", "report_id"),
        CheckConstraint("score IS NULL OR score BETWEEN 1 AND 5", name="ck_criterion_scores_score"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    report_id: Mapped[UUID] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"))
    criterion_id: Mapped[str] = mapped_column(String(60))
    outcome: Mapped[str] = mapped_column(String(30))
    score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    rationale: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSONB, default=list)
    verified: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
