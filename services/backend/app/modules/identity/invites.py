"""Invites and member administration (D45).

A link token is 32 random bytes; only its SHA-256 is stored. Before acceptance the invitee is not
a member of anything, so the invite is read through `invite_session`, where RLS shows exactly the
one row whose hash matches. Acceptance pins that invite's workspace in the same transaction and
writes the membership under the ordinary tenant policy.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.auth_admin import AccountExists, AuthAdmin
from app.db.models import Membership, Workspace
from app.db.session import invite_session, pin_workspace
from app.errors import AppError, ForbiddenError
from app.modules.identity.models import Invite
from app.modules.identity.service import ROLE_MANAGER, ROLE_OWNER, ROLE_RANK, ROLE_REP, Principal
from app.modules.platform import audit

INVITE_TTL = timedelta(days=7)
ROLES = (ROLE_REP, ROLE_MANAGER, ROLE_OWNER)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def invite_state(invite: Invite, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    if invite.accepted_at is not None:
        return "accepted"
    if invite.revoked_at is not None:
        return "revoked"
    if invite.expires_at <= now:
        return "expired"
    return "pending"


def _can_invite(principal: Principal, role: str) -> None:
    """Managers bring in reps; only an owner hands out manager or owner."""
    if role not in ROLES:
        raise AppError("invalid_role", f"Role must be one of {', '.join(ROLES)}", status_code=422)
    principal.require_role(ROLE_MANAGER)
    if ROLE_RANK[role] > ROLE_RANK[ROLE_REP]:
        principal.require_role(ROLE_OWNER)


async def create_invite(session: AsyncSession, principal: Principal, email: str, role: str) -> tuple[Invite, str]:
    _can_invite(principal, role)
    email = email.strip().lower()
    member = await session.scalar(select(Membership.id).where(
        Membership.workspace_id == principal.workspace_id, func.lower(Membership.email) == email))
    if member is not None:
        raise AppError("already_member", f"{email} is already in this workspace", status_code=409)
    token = secrets.token_urlsafe(32)
    invite = Invite(workspace_id=principal.workspace_id, email=email, role=role, token_hash=hash_token(token),
                    created_by=principal.user_id, expires_at=datetime.now(UTC) + INVITE_TTL)
    session.add(invite)
    await session.flush()
    await audit.record(session, principal.workspace_id, actor=principal.user_id, action="invite.created",
                       target_type="invite", target_id=invite.id, detail={"email": email, "role": role})
    return invite, token


async def list_invites(session: AsyncSession, principal: Principal) -> list[Invite]:
    principal.require_role(ROLE_MANAGER)
    rows = await session.execute(
        select(Invite).where(Invite.workspace_id == principal.workspace_id, Invite.accepted_at.is_(None),
                             Invite.revoked_at.is_(None)).order_by(Invite.created_at.desc())
    )
    return list(rows.scalars().all())


async def revoke_invite(session: AsyncSession, principal: Principal, invite_id: UUID) -> None:
    principal.require_role(ROLE_MANAGER)
    invite = await session.scalar(select(Invite).where(
        Invite.id == invite_id, Invite.workspace_id == principal.workspace_id).with_for_update())
    if invite is None:
        raise AppError("invite_not_found", "Invite not found", status_code=404)
    _can_invite(principal, invite.role)
    if invite_state(invite) != "pending":
        raise AppError("invite_not_pending", f"Invite is {invite_state(invite)}", status_code=409)
    invite.revoked_at = datetime.now(UTC)
    await audit.record(session, principal.workspace_id, actor=principal.user_id, action="invite.revoked",
                       target_type="invite", target_id=invite.id, detail={"email": invite.email})


@dataclass(frozen=True)
class InviteInfo:
    email: str
    role: str
    workspace_name: str
    state: str
    expires_at: datetime


async def _open(session: AsyncSession, token: str) -> Invite:
    invite = await session.scalar(select(Invite).where(Invite.token_hash == hash_token(token)))
    if invite is None:
        # Same answer for a wrong token and a deleted workspace: no probing.
        raise AppError("invite_not_found", "This invite link is not valid", status_code=404)
    return invite


def _require_pending(invite: Invite) -> None:
    state = invite_state(invite)
    if state != "pending":
        raise AppError(f"invite_{state}", f"This invite has been {state}. Ask for a new link.", status_code=410)


async def lookup(token: str) -> InviteInfo:
    async with invite_session(hash_token(token)) as session:
        invite = await _open(session, token)
        await pin_workspace(session, invite.workspace_id)
        workspace = await session.get(Workspace, invite.workspace_id)
        return InviteInfo(invite.email, invite.role, workspace.name if workspace else "", invite_state(invite),
                          invite.expires_at)


async def accept(token: str, *, user_id: UUID, email: str | None) -> Membership:
    """Join with an account the caller already holds (or one `accept_new` just made)."""
    async with invite_session(hash_token(token), user_id) as session:
        # No row lock here: FOR UPDATE would need the tenant policy, which is not pinned yet.
        # The conditional UPDATE below is the atomic claim.
        invite = await _open(session, token)
        _require_pending(invite)
        if (email or "").strip().lower() != invite.email:
            raise ForbiddenError(f"This invite is for {invite.email}. Sign in with that address.")
        # Read before the workspace is pinned: RLS then shows only this user's own memberships.
        existing = (await session.execute(select(Membership).where(Membership.user_id == user_id))).scalars().all()
        if any(m.workspace_id == invite.workspace_id for m in existing):
            raise AppError("already_member", "You are already in this workspace", status_code=409)
        if existing:
            # The web app has no workspace switcher yet, so a second membership would lock the
            # person out of both (every request would need X-Workspace-Id).
            raise AppError("already_in_workspace",
                           "This account already belongs to another workspace. Use a different email.",
                           status_code=409)
        await pin_workspace(session, invite.workspace_id)
        claimed = await session.execute(
            update(Invite).where(Invite.id == invite.id, Invite.accepted_at.is_(None),
                                 Invite.revoked_at.is_(None), Invite.expires_at > func.now())
            .values(accepted_at=datetime.now(UTC), accepted_by=user_id).returning(Invite.id)
        )
        if claimed.scalar_one_or_none() is None:
            raise AppError("invite_not_pending", "This invite is no longer valid. Ask for a new link.", status_code=410)
        membership = Membership(workspace_id=invite.workspace_id, user_id=user_id, role=invite.role,
                                email=invite.email)
        session.add(membership)
        await session.flush()
        await audit.record(session, invite.workspace_id, actor=user_id, action="invite.accepted",
                           target_type="member", target_id=user_id,
                           detail={"email": invite.email, "role": invite.role, "invite_id": str(invite.id)})
        return membership


async def accept_new(token: str, password: str, auth_admin: AuthAdmin) -> Membership:
    """Create the invitee's account, then join. An existing account must sign in instead."""
    async with invite_session(hash_token(token)) as session:
        invite = await _open(session, token)
        _require_pending(invite)
        email = invite.email
    try:
        user_id = await auth_admin.create_user(email, password)
    except AccountExists as exc:
        raise AppError("account_exists", f"{email} already has an account. Sign in to accept the invite.",
                       status_code=409) from exc
    return await accept(token, user_id=user_id, email=email)


# ---------------------------------------------------------------- members


async def _member(session: AsyncSession, workspace_id: UUID, user_id: UUID) -> Membership:
    row = await session.scalar(select(Membership).where(
        Membership.workspace_id == workspace_id, Membership.user_id == user_id).with_for_update())
    if row is None:
        raise AppError("member_not_found", "Member not found", status_code=404)
    return row


async def _owners(session: AsyncSession, workspace_id: UUID) -> int:
    return int(await session.scalar(select(func.count()).select_from(Membership).where(
        Membership.workspace_id == workspace_id, Membership.role == ROLE_OWNER)) or 0)


async def change_role(session: AsyncSession, principal: Principal, user_id: UUID, role: str) -> Membership:
    principal.require_role(ROLE_OWNER)
    if role not in ROLES:
        raise AppError("invalid_role", f"Role must be one of {', '.join(ROLES)}", status_code=422)
    row = await _member(session, principal.workspace_id, user_id)
    if row.role == role:
        return row
    if row.role == ROLE_OWNER and await _owners(session, principal.workspace_id) == 1:
        raise AppError("last_owner", "A workspace needs at least one owner", status_code=409)
    old, row.role = row.role, role
    await audit.record(session, principal.workspace_id, actor=principal.user_id, action="member.role_changed",
                       target_type="member", target_id=user_id, detail={"email": row.email, "from": old, "to": role})
    return row


async def remove_member(session: AsyncSession, principal: Principal, user_id: UUID) -> None:
    """Access ends at once; the member's past calls and reports stay with the workspace."""
    principal.require_role(ROLE_OWNER)
    row = await _member(session, principal.workspace_id, user_id)
    if row.role == ROLE_OWNER and await _owners(session, principal.workspace_id) == 1:
        raise AppError("last_owner", "A workspace needs at least one owner", status_code=409)
    await session.delete(row)
    await audit.record(session, principal.workspace_id, actor=principal.user_id, action="member.removed",
                       target_type="member", target_id=user_id, detail={"email": row.email, "role": row.role})
