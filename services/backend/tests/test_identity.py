from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from app.errors import AppError, ForbiddenError
from app.modules.identity import service
from app.modules.identity.service import (
    ROLE_MANAGER,
    ROLE_OWNER,
    ROLE_REP,
    Principal,
    resolve_membership,
)

WORKSPACE_A = uuid4()
WORKSPACE_B = uuid4()
USER = uuid4()


@dataclass
class FakeMembership:
    workspace_id: UUID
    role: str = ROLE_REP


def _with_memberships(monkeypatch: pytest.MonkeyPatch, memberships: list[FakeMembership]) -> None:
    async def fake_list(_session: object, _user_id: UUID) -> list[FakeMembership]:
        return memberships

    monkeypatch.setattr(service, "list_memberships", fake_list)


def test_roles_are_ordered_not_merely_distinct() -> None:
    owner = Principal(user_id=USER, workspace_id=WORKSPACE_A, role=ROLE_OWNER)
    rep = Principal(user_id=USER, workspace_id=WORKSPACE_A, role=ROLE_REP)
    assert owner.has_role(ROLE_MANAGER)
    assert not rep.has_role(ROLE_MANAGER)
    assert rep.has_role(ROLE_REP)


def test_unknown_role_grants_nothing() -> None:
    """A role string that predates or postdates this code must not be treated as owner."""
    stranger = Principal(user_id=USER, workspace_id=WORKSPACE_A, role="superuser")
    assert not stranger.has_role(ROLE_REP)
    with pytest.raises(ForbiddenError):
        stranger.require_role(ROLE_REP)


async def test_single_membership_is_selected_implicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_memberships(monkeypatch, [FakeMembership(WORKSPACE_A, ROLE_MANAGER)])
    membership = await resolve_membership(None, USER)
    assert membership.workspace_id == WORKSPACE_A
    assert membership.role == ROLE_MANAGER


async def test_several_memberships_require_an_explicit_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_memberships(monkeypatch, [FakeMembership(WORKSPACE_A), FakeMembership(WORKSPACE_B)])
    with pytest.raises(AppError) as exc:
        await resolve_membership(None, USER)
    assert exc.value.code == "workspace_required"

    chosen = await resolve_membership(None, USER, WORKSPACE_B)
    assert chosen.workspace_id == WORKSPACE_B


async def test_foreign_workspace_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_memberships(monkeypatch, [FakeMembership(WORKSPACE_A)])
    with pytest.raises(ForbiddenError):
        await resolve_membership(None, USER, WORKSPACE_B)


async def test_user_without_memberships_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_memberships(monkeypatch, [])
    with pytest.raises(ForbiddenError):
        await resolve_membership(None, USER)
