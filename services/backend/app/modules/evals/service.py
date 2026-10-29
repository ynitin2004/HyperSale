"""Rater labelling (D37). Blind by construction: nothing here reads scoring tables.

A rater reads every item in the workspace but only their own labels; RLS confines both to the
Evals workspace, the service confines labels to the caller.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AppError
from app.modules.evals.models import EvalItem, EvalLabel
from app.modules.identity.service import Principal

OUTCOMES = ("1", "2", "3", "4", "5", "insufficient_evidence")


@dataclass
class ItemProgress:
    item: EvalItem
    labelled: int


async def list_items(session: AsyncSession, principal: Principal) -> list[ItemProgress]:
    items = list((await session.execute(
        select(EvalItem).where(EvalItem.workspace_id == principal.workspace_id).order_by(EvalItem.item_key)
    )).scalars().all())
    counts = dict((await session.execute(
        select(EvalLabel.item_id, func.count()).where(
            EvalLabel.workspace_id == principal.workspace_id, EvalLabel.rater_user_id == principal.user_id,
        ).group_by(EvalLabel.item_id)
    )).all())
    return [ItemProgress(i, counts.get(i.id, 0)) for i in items]


async def get_item(session: AsyncSession, principal: Principal, item_id: UUID) -> tuple[EvalItem, dict[str, str], str | None]:
    item = (await session.execute(
        select(EvalItem).where(EvalItem.id == item_id, EvalItem.workspace_id == principal.workspace_id)
    )).scalar_one_or_none()
    if item is None:
        raise AppError("eval_item_not_found", "Item not found", status_code=404)
    mine = (await session.execute(select(EvalLabel).where(
        EvalLabel.item_id == item_id, EvalLabel.rater_user_id == principal.user_id,
    ))).scalars().all()
    note = next((m.note for m in mine if m.note), None)
    return item, {m.criterion_id: m.outcome for m in mine}, note


async def save_labels(
    session: AsyncSession, principal: Principal, item_id: UUID, labels: dict[str, str], note: str | None,
) -> dict[str, str]:
    item, _, _ = await get_item(session, principal, item_id)
    unknown = set(labels) - set(item.applicable_criteria)
    bad = {k: v for k, v in labels.items() if v not in OUTCOMES}
    if unknown or bad:
        raise AppError("invalid_labels", f"unknown criteria {sorted(unknown)} or outcomes {bad}", status_code=422)
    # Replace this rater's labels for the item in one transaction.
    await session.execute(delete(EvalLabel).where(
        EvalLabel.item_id == item_id, EvalLabel.rater_user_id == principal.user_id,
    ))
    for criterion_id, outcome in labels.items():
        session.add(EvalLabel(workspace_id=principal.workspace_id, item_id=item_id,
                              rater_user_id=principal.user_id, criterion_id=criterion_id,
                              outcome=outcome, note=note))
    await session.flush()
    return labels
