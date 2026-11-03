"""Workspace settings (D46) and the monthly spend limit (D47).

A workspace without a settings row runs on the defaults; the first owner save creates the row.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UsageEvent
from app.errors import AppError
from app.modules.platform import audit
from app.modules.platform.models import (
    DEFAULT_AUDIO_RETENTION_DAYS,
    DEFAULT_MONTHLY_LIMIT_MICROUSD,
    WorkspaceSettings,
)


@dataclass(frozen=True)
class SettingsView:
    audio_retention_days: int | None
    monthly_limit_microusd: int | None
    record_roleplay_audio: bool


DEFAULTS = SettingsView(DEFAULT_AUDIO_RETENTION_DAYS, DEFAULT_MONTHLY_LIMIT_MICROUSD, True)


def _view(row: WorkspaceSettings | None) -> SettingsView:
    if row is None:
        return DEFAULTS
    return SettingsView(row.audio_retention_days, row.monthly_limit_microusd, row.record_roleplay_audio)


async def get(session: AsyncSession, workspace_id: UUID) -> SettingsView:
    return _view(await session.get(WorkspaceSettings, workspace_id))


async def update(session: AsyncSession, workspace_id: UUID, actor: UUID, new: SettingsView) -> SettingsView:
    row = await session.get(WorkspaceSettings, workspace_id)
    old = _view(row)
    if row is None:
        row = WorkspaceSettings(workspace_id=workspace_id)
        session.add(row)
    row.audio_retention_days = new.audio_retention_days
    row.monthly_limit_microusd = new.monthly_limit_microusd
    row.record_roleplay_audio = new.record_roleplay_audio
    row.updated_by = actor
    row.updated_at = datetime.now(UTC)
    changed = {k: {"from": v, "to": getattr(new, k)} for k, v in vars(old).items() if v != getattr(new, k)}
    if changed:
        await audit.record(session, workspace_id, actor=actor, action="settings.updated",
                           target_type="workspace", target_id=workspace_id, detail=changed)
    await session.flush()
    return new


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def month_spend(session: AsyncSession, workspace_id: UUID) -> int:
    total = await session.scalar(
        select(func.coalesce(func.sum(UsageEvent.cost_microusd), 0))
        .where(UsageEvent.workspace_id == workspace_id, UsageEvent.created_at >= month_start())
    )
    return int(total or 0)


def _usd(microusd: int) -> str:
    return f"${microusd / 1_000_000:.2f}"


async def check_spend(session: AsyncSession, workspace_id: UUID) -> None:
    """D47: refuse new paid work at or over the limit. Work already running is not stopped."""
    limit = (await get(session, workspace_id)).monthly_limit_microusd
    if limit is None:
        return
    spent = await month_spend(session, workspace_id)
    if spent >= limit:
        raise AppError(
            "spend_limit_reached",
            f"This workspace has used {_usd(spent)} of its {_usd(limit)} monthly AI limit. "
            "An owner can raise it in Settings.",
            status_code=402,
        )
