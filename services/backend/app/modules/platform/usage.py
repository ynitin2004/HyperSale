"""Usage metering — the ledger behind "honest cost per roleplay minute".

Rates are configuration, not constants baked into code. When a rate has not been measured
yet the event is still recorded with `rate_missing`, so a zero cost is visibly unknown
rather than silently free.
"""
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings

EVENT_REALTIME_AUDIO = "realtime_audio"
EVENT_TRANSCRIPTION = "transcription"
EVENT_SCORING = "scoring"

_INSERT_USAGE = text("""
    INSERT INTO usage_events (
        workspace_id, event_type, provider, model_id,
        input_units, output_units, cost_microusd, metadata, dedupe_key
    )
    VALUES (
        :workspace_id, :event_type, :provider, :model_id,
        :input_units, :output_units, :cost_microusd, CAST(:metadata AS jsonb), :dedupe_key
    )
    ON CONFLICT ON CONSTRAINT uq_usage_events_dedupe DO NOTHING
    RETURNING id
""")

_FIND_BY_DEDUPE_KEY = text("""
    SELECT id FROM usage_events
    WHERE workspace_id = :workspace_id AND dedupe_key = :dedupe_key
""")

_SUMMARY = text("""
    SELECT event_type,
           count(*) AS events,
           sum(input_units) AS input_units,
           sum(output_units) AS output_units,
           sum(cost_microusd) AS cost_microusd,
           bool_or(coalesce((metadata->>'rate_missing')::boolean, false)) AS rate_missing
    FROM usage_events
    WHERE workspace_id = :workspace_id AND created_at >= :since
    GROUP BY event_type
    ORDER BY event_type
""")


@dataclass(frozen=True)
class UsageCost:
    cost_microusd: int
    rate_missing: bool


def realtime_audio_cost(
    input_seconds: float, output_seconds: float, settings: Settings | None = None
) -> UsageCost:
    """Cost of one realtime exchange. Seconds in, micro-USD out; no float money."""
    settings = settings or get_settings()
    if input_seconds < 0 or output_seconds < 0:
        raise ValueError("Audio duration cannot be negative")

    in_rate = settings.realtime_audio_input_microusd_per_minute
    out_rate = settings.realtime_audio_output_microusd_per_minute
    rate_missing = (input_seconds > 0 and in_rate <= 0) or (output_seconds > 0 and out_rate <= 0)
    cost = round(in_rate * input_seconds / 60) + round(out_rate * output_seconds / 60)
    return UsageCost(cost_microusd=int(cost), rate_missing=rate_missing)


async def record_usage(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    event_type: str,
    provider: str | None = None,
    model_id: str | None = None,
    input_units: int = 0,
    output_units: int = 0,
    cost: UsageCost | None = None,
    metadata: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
) -> UUID:
    """Record one metered event. With a `dedupe_key` the write is safely re-runnable."""
    payload = dict(metadata or {})
    if cost is not None:
        payload["rate_missing"] = cost.rate_missing
    params = {
        "workspace_id": str(workspace_id),
        "event_type": event_type,
        "provider": provider,
        "model_id": model_id,
        "input_units": input_units,
        "output_units": output_units,
        "cost_microusd": cost.cost_microusd if cost else 0,
        "metadata": json.dumps(payload),
        "dedupe_key": dedupe_key,
    }
    inserted = (await session.execute(_INSERT_USAGE, params)).scalar_one_or_none()
    if inserted is not None:
        return inserted
    if dedupe_key is None:
        # Unreachable: a NULL key cannot conflict. Loud beats a confusing lookup failure.
        raise RuntimeError("Usage insert was skipped without a dedupe key")
    # A retried job re-ran a write that already landed; return the original row.
    return (
        await session.execute(
            _FIND_BY_DEDUPE_KEY,
            {"workspace_id": params["workspace_id"], "dedupe_key": dedupe_key},
        )
    ).scalar_one()


async def usage_summary(
    session: AsyncSession, workspace_id: UUID, since: datetime
) -> list[dict[str, Any]]:
    result = await session.execute(
        _SUMMARY, {"workspace_id": str(workspace_id), "since": since}
    )
    return [dict(row) for row in result.mappings().all()]
