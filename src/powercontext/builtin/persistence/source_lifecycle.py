"""Durable lifecycle graphs and Topic retrieval exclusions."""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.builtin.persistence.tables import (
    LIFECYCLE_GRAPHS,
    LIFECYCLE_HIDDEN_TOPICS,
    LIFECYCLE_TABLES,
)

__all__ = ["LIFECYCLE_GRAPHS", "LIFECYCLE_HIDDEN_TOPICS", "LIFECYCLE_TABLES"]


async def retained_memory_entry_ids(
    connection: AsyncConnection, scope_id: str, memory_artifact_id: str
) -> frozenset[str]:
    """Protect native logical entries while durable lifecycle bindings own them."""

    value = await connection.scalar(select(LIFECYCLE_GRAPHS.c.graph).where(LIFECYCLE_GRAPHS.c.scope_id == scope_id))
    if value is None:
        return frozenset()
    return frozenset(
        node["reference"]["entry_id"]
        for node in json.loads(value)["nodes"].values()
        if node["kind"] == "memory" and node["reference"]["memory_ref"]["artifact_id"] == memory_artifact_id
    )
