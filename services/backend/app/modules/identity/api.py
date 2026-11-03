from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.adapters.auth_admin import build_auth_admin
from app.db.session import identity_session, tenant_session
from app.errors import AppError
from app.modules.identity import invites
from app.modules.identity.deps import CurrentPrincipal, TenantSession, bearer_scheme, current_claims
from app.modules.identity.service import list_members, list_memberships, record_email
from app.modules.identity.tokens import TokenClaims, get_verifier

router = APIRouter()

Role = Literal["rep", "manager", "owner"]


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
    async with tenant_session(principal.workspace_id) as session:
        await record_email(session, principal)
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


# ---------------------------------------------------------------- members and invites (D45)

# Deliberately loose: Supabase does the real check when the account is created.
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class MemberOut(BaseModel):
    user_id: UUID
    email: str | None
    role: str
    created_at: datetime


class RoleIn(BaseModel):
    role: Role


class InviteIn(BaseModel):
    email: str = Field(max_length=320, pattern=EMAIL_PATTERN)
    role: Role = "rep"


class InviteOut(BaseModel):
    id: UUID
    email: str
    role: str
    state: str
    created_at: datetime
    expires_at: datetime


class InviteCreatedOut(InviteOut):
    # Shown once; only its hash is stored, so a lost link means a new invite.
    token: str


class InviteLookupOut(BaseModel):
    email: str
    role: str
    workspace_name: str
    state: str
    expires_at: datetime


class AcceptIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    # Only for a new account. Signed-in callers send their bearer token instead.
    password: str | None = Field(default=None, min_length=8, max_length=200)


class AcceptOut(BaseModel):
    workspace_id: UUID
    role: str
    email: str


def _invite_out(row) -> InviteOut:
    return InviteOut(id=row.id, email=row.email, role=row.role, state=invites.invite_state(row),
                     created_at=row.created_at, expires_at=row.expires_at)


@router.get("/members", response_model=list[MemberOut])
async def members(principal: CurrentPrincipal, session: TenantSession) -> list[MemberOut]:
    principal.require_role("manager")
    return [MemberOut(user_id=m.user_id, email=m.email, role=m.role, created_at=m.created_at)
            for m in await list_members(session, principal.workspace_id)]


@router.patch("/members/{user_id}", response_model=MemberOut)
async def change_member_role(user_id: UUID, body: RoleIn, principal: CurrentPrincipal,
                             session: TenantSession) -> MemberOut:
    m = await invites.change_role(session, principal, user_id, body.role)
    return MemberOut(user_id=m.user_id, email=m.email, role=m.role, created_at=m.created_at)


@router.delete("/members/{user_id}", status_code=204)
async def remove_member(user_id: UUID, principal: CurrentPrincipal, session: TenantSession) -> Response:
    await invites.remove_member(session, principal, user_id)
    return Response(status_code=204)


@router.post("/invites", response_model=InviteCreatedOut, status_code=201)
async def create_invite(body: InviteIn, principal: CurrentPrincipal, session: TenantSession) -> InviteCreatedOut:
    row, token = await invites.create_invite(session, principal, body.email, body.role)
    return InviteCreatedOut(**_invite_out(row).model_dump(), token=token)


@router.get("/invites", response_model=list[InviteOut])
async def list_invites(principal: CurrentPrincipal, session: TenantSession) -> list[InviteOut]:
    return [_invite_out(r) for r in await invites.list_invites(session, principal)]


@router.delete("/invites/{invite_id}", status_code=204)
async def revoke_invite(invite_id: UUID, principal: CurrentPrincipal, session: TenantSession) -> Response:
    await invites.revoke_invite(session, principal, invite_id)
    return Response(status_code=204)


@router.get("/invites/lookup", response_model=InviteLookupOut)
async def lookup_invite(token: str) -> InviteLookupOut:
    """Unauthenticated: the join page shows who invited the visitor, and as what."""
    return InviteLookupOut(**vars(await invites.lookup(token)))


@router.post("/invites/accept", response_model=AcceptOut)
async def accept_invite(
    body: AcceptIn,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AcceptOut:
    if credentials and credentials.credentials:
        claims = await get_verifier().verify(credentials.credentials)
        m = await invites.accept(body.token, user_id=claims.user_id, email=claims.email)
    elif body.password:
        m = await invites.accept_new(body.token, body.password, build_auth_admin())
    else:
        raise AppError("password_required", "Choose a password, or sign in first", status_code=422)
    return AcceptOut(workspace_id=m.workspace_id, role=m.role, email=m.email or "")
