"""M4 rules that need no database: invite permissions and states (D45), the spend month (D47)."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.errors import AppError, ForbiddenError
from app.modules.identity.invites import _can_invite, hash_token, invite_state
from app.modules.identity.models import Invite
from app.modules.identity.service import Principal
from app.modules.platform.workspace_settings import month_start


def _principal(role: str) -> Principal:
    return Principal(user_id=uuid4(), workspace_id=uuid4(), role=role)


@pytest.mark.parametrize(("inviter", "role", "allowed"), [
    ("rep", "rep", False), ("manager", "rep", True), ("manager", "manager", False),
    ("manager", "owner", False), ("owner", "manager", True), ("owner", "owner", True),
])
def test_managers_invite_reps_and_only_owners_invite_above(inviter: str, role: str, allowed: bool) -> None:
    if allowed:
        _can_invite(_principal(inviter), role)
    else:
        with pytest.raises(ForbiddenError):
            _can_invite(_principal(inviter), role)


def test_unknown_role_is_rejected_before_permissions() -> None:
    with pytest.raises(AppError) as exc:
        _can_invite(_principal("owner"), "admin")
    assert exc.value.code == "invalid_role"


def test_only_the_token_hash_is_stored() -> None:
    token = "a" * 43
    assert hash_token(token) != token and len(hash_token(token)) == 64
    assert hash_token(token) == hash_token(token)


def test_invite_state_order() -> None:
    now = datetime.now(UTC)
    invite = Invite(expires_at=now + timedelta(days=1))
    assert invite_state(invite, now) == "pending"
    invite.expires_at = now - timedelta(seconds=1)
    assert invite_state(invite, now) == "expired"
    invite.revoked_at = now
    assert invite_state(invite, now) == "revoked"
    invite.accepted_at = now  # accepted wins: it is what actually happened
    assert invite_state(invite, now) == "accepted"


def test_spend_month_starts_at_utc_midnight_on_the_first() -> None:
    assert month_start(datetime(2026, 11, 30, 23, 59, tzinfo=UTC)) == datetime(2026, 11, 1, tzinfo=UTC)
