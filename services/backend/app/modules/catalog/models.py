"""Catalog tables: global, read-only product content (D30). Written only by the seed script."""
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
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


class Persona(Base):
    __tablename__ = "personas"
    __table_args__ = (UniqueConstraint("slug", "prompt_version", name="uq_personas_slug_version"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(200))
    company: Mapped[str] = mapped_column(String(200))
    voice: Mapped[str] = mapped_column(String(80))
    instructions: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RubricVersion(Base):
    __tablename__ = "rubric_versions"
    version: Mapped[str] = mapped_column(String(40), primary_key=True)
    criteria: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Scenario(Base):
    __tablename__ = "scenarios"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_scenarios_slug"),
        Index("ix_scenarios_persona", "persona_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(80))
    persona_id: Mapped[UUID] = mapped_column(ForeignKey("personas.id"))
    rubric_version: Mapped[str] = mapped_column(ForeignKey("rubric_versions.version"))
    title: Mapped[str] = mapped_column(String(200))
    brief: Mapped[str] = mapped_column(Text)
    call_type: Mapped[str] = mapped_column(String(40))
    difficulty: Mapped[str] = mapped_column(String(20))
    applicable_criteria: Mapped[list] = mapped_column(JSONB)
    featured: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Drill(Base):
    __tablename__ = "drills"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    criterion_id: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(200))
    instructions: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
