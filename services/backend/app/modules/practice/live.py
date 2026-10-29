"""In-process registry of live calls - the state D29 accepted into `api`.

One `LiveSession` per connected roleplay holds the provider call, consumes its domain events
(persisting each transcript turn as it completes), enforces the session cap, and finalizes
exactly once - whichever comes first of: the rep pressing End, the cap, the provider closing,
or api shutdown. Finalizing writes the server-measured usage and creates the report + scoring
job in one transaction.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.adapters.voice import LiveCall
from app.db.session import system_session, tenant_session
from app.modules.platform.usage import (
    EVENT_REALTIME_AUDIO,
    RealtimeTokens,
    realtime_token_cost,
    record_usage,
)
from app.modules.practice import service as practice

log = logging.getLogger("hypersale.practice.live")

REP_PREFIX_PADDING_MS = 300
FINALIZE_DRAIN_SECONDS = 3.0


def add_usage(totals: dict[str, int], usage: dict[str, Any]) -> None:
    ind = usage.get("input_token_details") or {}
    outd = usage.get("output_token_details") or {}
    cached = ind.get("cached_tokens_details") or {}
    cached_text = cached.get("text_tokens", 0) or 0
    cached_audio = cached.get("audio_tokens", 0) or 0
    totals["text_in"] += max(0, (ind.get("text_tokens", 0) or 0) - cached_text)
    totals["audio_in"] += max(0, (ind.get("audio_tokens", 0) or 0) - cached_audio)
    totals["text_in_cached"] += cached_text
    totals["audio_in_cached"] += cached_audio
    totals["text_out"] += outd.get("text_tokens", 0) or 0
    totals["audio_out"] += outd.get("audio_tokens", 0) or 0
    totals["responses"] += 1


# Plausibility caps for browser-reported usage (D32): realtime audio is ~10 tokens per
# second per direction, so anything far beyond the call's length is rejected, not billed.
AUDIO_TOKENS_PER_SECOND_CAP = 40
TEXT_TOKENS_PER_RESPONSE_CAP = 20_000


def bound_client_usage(client: dict[str, int], duration_ms: int) -> dict[str, int]:
    seconds = max(1, duration_ms // 1000)
    responses = max(1, min(int(client.get("responses", 1) or 1), seconds))
    audio_cap = seconds * AUDIO_TOKENS_PER_SECOND_CAP
    text_cap = responses * TEXT_TOKENS_PER_RESPONSE_CAP
    out = empty_usage()
    for key in ("audio_in", "audio_in_cached", "audio_out"):
        out[key] = max(0, min(int(client.get(key, 0) or 0), audio_cap))
    for key in ("text_in", "text_in_cached", "text_out"):
        out[key] = max(0, min(int(client.get(key, 0) or 0), text_cap))
    out["responses"] = responses
    return out


def empty_usage() -> dict[str, int]:
    return dict.fromkeys(("text_in", "text_in_cached", "audio_in", "audio_in_cached",
                          "text_out", "audio_out", "responses"), 0)


@dataclass
class LiveSession:
    session_id: UUID
    workspace_id: UUID
    user_id: UUID
    call: LiveCall
    cap_seconds: int
    connect_ms: int
    started_at: float = field(default_factory=time.monotonic)
    usage: dict[str, int] = field(default_factory=empty_usage)
    starts: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    end_reason: str | None = None
    client_usage: dict[str, int] | None = None
    turn_starts: dict[str, int] | None = None
    consumer: asyncio.Task | None = None
    cap_timer: asyncio.Task | None = None
    finalized: asyncio.Future | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class LiveRegistry:
    def __init__(self) -> None:
        self._sessions: dict[UUID, LiveSession] = {}

    def get(self, session_id: UUID) -> LiveSession | None:
        return self._sessions.get(session_id)

    def __len__(self) -> int:
        return len(self._sessions)

    def start(self, live: LiveSession) -> None:
        live.finalized = asyncio.get_running_loop().create_future()
        self._sessions[live.session_id] = live
        live.consumer = asyncio.create_task(self._consume(live), name=f"call-{live.session_id}")
        live.cap_timer = asyncio.create_task(self._cap(live), name=f"cap-{live.session_id}")

    async def _cap(self, live: LiveSession) -> None:
        await asyncio.sleep(live.cap_seconds)
        log.info("session cap reached", extra={"session_id": str(live.session_id)})
        live.end_reason = live.end_reason or "cap_reached"
        await live.call.close()

    async def _consume(self, live: LiveSession) -> None:
        try:
            async for event in live.call.events():
                try:
                    await self._handle(live, event)
                except Exception:  # noqa: BLE001 - one bad event must not end the call
                    log.exception("failed to handle voice event",
                                  extra={"session_id": str(live.session_id), "kind": event.kind})
        except Exception:  # noqa: BLE001
            log.exception("voice event stream failed", extra={"session_id": str(live.session_id)})
            live.end_reason = live.end_reason or "provider_error"
        # The provider ended the call (or we hung up). Finalize in the background so the
        # report exists even if the browser never calls /end.
        live.end_reason = live.end_reason or "provider_closed"
        asyncio.create_task(self.finalize(live.session_id, live.end_reason))

    async def _handle(self, live: LiveSession, event: Any) -> None:
        if event.kind in ("rep_started", "buyer_started") and event.item_id:
            live.starts.setdefault(event.item_id, event.at_ms)
        elif event.kind in ("rep_transcript", "buyer_transcript") and event.item_id and event.text:
            speaker = "rep" if event.kind == "rep_transcript" else "buyer"
            start = live.starts.get(event.item_id)
            if start is None:
                start = event.at_ms
            if speaker == "rep":
                start = max(0, start - REP_PREFIX_PADDING_MS)
            async with tenant_session(live.workspace_id, live.user_id) as session:
                await practice.upsert_turn(
                    session, live.workspace_id, live.session_id, item_id=event.item_id,
                    speaker=speaker, text_=event.text, start_ms=start,
                    end_ms=max(event.at_ms, start + 400),
                )
        elif event.kind == "usage":
            add_usage(live.usage, event.usage)
        elif event.kind == "error":
            live.errors.append(event.detail or "unknown")

    async def end(
        self, session_id: UUID, reason: str, *, client_usage: dict[str, int] | None = None,
        turn_starts: dict[str, int] | None = None,
    ) -> UUID | None:
        live = self._sessions.get(session_id)
        if live is None:
            return None
        live.end_reason = live.end_reason or reason
        live.client_usage = client_usage
        live.turn_starts = turn_starts
        return await self.finalize(session_id, live.end_reason)

    async def finalize(self, session_id: UUID, reason: str) -> UUID | None:
        """Exactly once per session; concurrent callers all receive the same report id."""
        live = self._sessions.get(session_id)
        if live is None:
            return None
        async with live.lock:
            if live.finalized is not None and live.finalized.done():
                return live.finalized.result()
            await live.call.close()
            if live.cap_timer:
                live.cap_timer.cancel()
            if live.consumer and live.consumer is not asyncio.current_task():
                # Let in-flight transcript writes land before reading the transcript.
                with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                    await asyncio.wait_for(asyncio.shield(live.consumer), FINALIZE_DRAIN_SECONDS)
            try:
                report_id = await finalize_session(
                    workspace_id=live.workspace_id, user_id=live.user_id, session_id=session_id,
                    reason=reason, usage=live.usage, errors=live.errors,
                    event_counts=getattr(live.call, "event_counts", None),
                    client_usage=live.client_usage, turn_starts=live.turn_starts,
                )
            except Exception as exc:
                log.exception("finalize failed", extra={"session_id": str(session_id)})
                if live.finalized and not live.finalized.done():
                    live.finalized.set_exception(exc)
                self._sessions.pop(session_id, None)
                raise
            if live.finalized and not live.finalized.done():
                live.finalized.set_result(report_id)
            self._sessions.pop(session_id, None)
            return report_id

    async def shutdown(self) -> None:
        for session_id in list(self._sessions):
            with contextlib.suppress(Exception):
                await self.finalize(session_id, "api_shutdown")


async def finalize_session(
    *, workspace_id: UUID, user_id: UUID, session_id: UUID, reason: str,
    usage: dict[str, int] | None, errors: list[str] | None = None,
    event_counts: dict[str, int] | None = None,
    client_usage: dict[str, int] | None = None,
    turn_starts: dict[str, int] | None = None,
) -> UUID:
    # Imported here: scoring depends on practice, so practice reaches scoring lazily.
    from app.modules.scoring import service as scoring

    ended_at = datetime.now(UTC)
    interrupted = reason in ("provider_closed", "provider_error", "api_shutdown", "api_restart")
    async with tenant_session(workspace_id, user_id) as session:
        row = await practice.get_session_by_id(session, workspace_id, session_id)
        if row is None:
            raise LookupError(f"session {session_id} not found")
        existing = await scoring.report_for_session(session, session_id)
        if existing is not None and row.status in practice.FINAL_STATUSES:
            return existing.id
        if turn_starts:
            await practice.apply_turn_starts(session, session_id, turn_starts)
        await practice.renumber_turns(session, session_id)
        await practice.mark_ended(
            session, row, status="interrupted" if interrupted else "ended", reason=reason,
            timings={"provider_errors": len(errors or []), "provider_events": event_counts or {},
                     "usage_responses": (usage or {}).get("responses", 0)},
        )
        source = "server_socket"
        if not (usage and usage.get("responses")) and client_usage:
            # D32: usage only reaches the browser. Accept it within physical bounds.
            usage = bound_client_usage(client_usage, row.duration_ms or 0)
            source = "data_channel"
        if usage and usage.get("responses") and row.session_ref:
            tokens = RealtimeTokens(**{k: v for k, v in usage.items() if k != "responses"})
            await record_usage(
                session, workspace_id=workspace_id, event_type=EVENT_REALTIME_AUDIO,
                provider=row.provider, model_id=row.model_id,
                input_units=tokens.input_total, output_units=tokens.output_total,
                cost=realtime_token_cost(tokens),
                metadata={"session_ref": row.session_ref, "source": source, "unit": "tokens",
                          "tokens": {k: v for k, v in usage.items()}, "practice_session_id": str(session_id),
                          "duration_ms": row.duration_ms},
                dedupe_key=f"realtime:{row.session_ref}",
            )
        turns = await practice.get_transcript(session, session_id)
        report = await scoring.create_report(
            session, workspace_id=workspace_id, session_id=session_id,
            rubric_version=row.rubric_version, turns=turns, ended_at=ended_at,
        )
        return report.id


async def sweep_orphans() -> int:
    """After an api restart no socket survives: close out sessions left `live` (D29)."""
    from sqlalchemy import text

    async with system_session() as session:
        rows = (await session.execute(text(
            "SELECT id, workspace_id, user_id FROM practice_sessions "
            "WHERE status IN ('connecting', 'live')"
        ))).all()
    for row in rows:
        with contextlib.suppress(Exception):
            await finalize_session(workspace_id=row.workspace_id, user_id=row.user_id,
                                   session_id=row.id, reason="api_restart", usage=None)
    return len(rows)


registry = LiveRegistry()
