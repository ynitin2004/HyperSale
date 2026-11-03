"""Append-only audit log (D47). The table has no UPDATE or DELETE policy, so this module only adds."""
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.platform.models import AuditEvent

AUDIT_PAGE = 100


async def record(
    session: AsyncSession, workspace_id: UUID, *, actor: UUID | None, action: str, target_type: str,
    target_id: str | UUID | None = None, detail: dict[str, Any] | None = None,
) -> None:
    session.add(AuditEvent(
        workspace_id=workspace_id, actor_user_id=actor, action=action, target_type=target_type,
        target_id=str(target_id) if target_id is not None else None, detail=detail or {},
    ))
    await session.flush()


async def recent(session: AsyncSession, workspace_id: UUID, limit: int = AUDIT_PAGE) -> list[AuditEvent]:
    rows = await session.execute(
        select(AuditEvent).where(AuditEvent.workspace_id == workspace_id)
        .order_by(AuditEvent.created_at.desc()).limit(limit)
    )
    return list(rows.scalars().all())
