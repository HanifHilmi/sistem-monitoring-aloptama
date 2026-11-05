"""Append-only audit log (FR-AUD-001). Entries are written in the same transaction as the change they record."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def record(
    conn: AsyncConnection,
    action: str,
    *,
    actor: str | None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    source_ip: str | None = None,
) -> None:
    await conn.execute(
        text("""
        INSERT INTO audit_event (actor, action, entity_type, entity_id, before, after, source_ip)
        VALUES (:actor, :action, :et, :eid, CAST(:before AS jsonb), CAST(:after AS jsonb), :ip)
    """),
        {
            "actor": actor,
            "action": action,
            "et": entity_type,
            "eid": entity_id[:100] if entity_id else None,
            "before": json.dumps(before, default=str) if before is not None else None,
            "after": json.dumps(after, default=str) if after is not None else None,
            "ip": source_ip,
        },
    )


def diff(before: dict[str, Any], after: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Only the fields that changed, as (before, after)."""
    keys = [k for k in after if before.get(k) != after.get(k)]
    return {k: before.get(k) for k in keys}, {k: after[k] for k in keys}
