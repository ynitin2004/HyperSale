"""Workspace membership resolution — the first tenancy boundary.

A verified token proves *who* the caller is. Only a membership row proves *which workspace*
they may act in, so every request resolves one before any workspace data is touched.
"""
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Membership
from app.errors import AppError, ForbiddenError

ROLE_REP = "rep"
ROLE_MANAGER = "manager"
ROLE_OWNER = "owner"
ROLE_RANK: dict[str, int] = {ROLE_REP: 0, ROLE_MANAGER: 1, ROLE_OWNER: 2}


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    workspace_id: UUID
    role: str
    email: str | None = None

    def has_role(self, minimum: str) -> bool:
        required = ROLE_RANK[minimum]
        return ROLE_RANK.get(self.role, -1) >= required

    def require_role(self, minimum: str) -> None:
        if not self.has_role(minimum):
            raise ForbiddenError(f"Role {minimum!r} or higher is required")


async def list_memberships(session: AsyncSession, user_id: UUID) -> list[Membership]:
    result = await session.execute(
        select(Membership).where(Membership.user_id == user_id).order_by(Membership.created_at)
    )
    return list(result.scalars().all())


async def resolve_membership(
    session: AsyncSession, user_id: UUID, workspace_id: UUID | None = None
) -> Membership:
    memberships = await list_memberships(session, user_id)
    if not memberships:
        raise ForbiddenError("This user does not belong to any workspace")

    if workspace_id is not None:
        for membership in memberships:
            if membership.workspace_id == workspace_id:
                return membership
        # Same answer whether the workspace is missing or merely not theirs: no probing.
        raise ForbiddenError("This user does not belong to the requested workspace")

    if len(memberships) > 1:
        raise AppError(
            "workspace_required",
            "This user belongs to several workspaces; send X-Workspace-Id",
            status_code=400,
        )
    return memberships[0]
