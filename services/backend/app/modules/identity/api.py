from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.db.session import identity_session
from app.modules.identity.deps import CurrentPrincipal, current_claims
from app.modules.identity.service import list_memberships
from app.modules.identity.tokens import TokenClaims

router = APIRouter()


class WorkspaceMembership(BaseModel):
    workspace_id: UUID
    role: str


class MeResponse(BaseModel):
    user_id: UUID
    email: str | None
    workspace_id: UUID
    role: str


@router.get("/me", response_model=MeResponse)
async def current_user(principal: CurrentPrincipal) -> MeResponse:
    return MeResponse(
        user_id=principal.user_id,
        email=principal.email,
        workspace_id=principal.workspace_id,
        role=principal.role,
    )


@router.get("/me/workspaces", response_model=list[WorkspaceMembership])
async def my_workspaces(
    claims: Annotated[TokenClaims, Depends(current_claims)],
) -> list[WorkspaceMembership]:
    """Runs before a workspace is chosen, so it reads claims rather than a principal."""
    async with identity_session(claims.user_id) as session:
        memberships = await list_memberships(session, claims.user_id)
    return [WorkspaceMembership(workspace_id=m.workspace_id, role=m.role) for m in memberships]
