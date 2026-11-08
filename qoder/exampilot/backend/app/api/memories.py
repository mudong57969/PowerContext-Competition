"""Memory endpoints: local audit log + PowerContext search / explicit writes."""

from __future__ import annotations

from fastapi import APIRouter, Header

from app.api.deps import (
    get_memory_service,
    remember_for_session,
    require_session,
    session_scope_id,
)
from app.api.schemas import MemoryEventOut, MemoryWriteRequest
from app.core.seekdb import get_engine
from app.memory.powercontext import MemoryUnavailableError

router = APIRouter(prefix="/api/sessions", tags=["memories"])


@router.get("/{session_id}/memories", response_model=list[MemoryEventOut])
def memory_events(
    session_id: str, authorization: str | None = Header(default=None)
) -> list[MemoryEventOut]:
    require_session(session_id, authorization)
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, session_id, kind, summary, memory_reference, status, created_at "
            "FROM memory_events WHERE session_id=%s ORDER BY id DESC LIMIT 100",
            (session_id,),
        )
        return [
            MemoryEventOut(
                id=int(row[0]),
                session_id=str(row[1]),
                kind=str(row[2]),
                summary=str(row[3]),
                memory_reference=str(row[4]) if row[4] else None,
                status=str(row[5]),
                created_at=row[6],
            )
            for row in cur.fetchall()
        ]


@router.get("/{session_id}/memories/search")
def memory_search(
    session_id: str,
    query: str,
    limit: int = 10,
    authorization: str | None = Header(default=None),
) -> dict:
    require_session(session_id, authorization)
    scope_id = session_scope_id(session_id)
    if not scope_id:
        return {
            "available": False,
            "warning": "session has no PowerContext scope",
            "hits": [],
            "mode": None,
        }
    try:
        outcome = get_memory_service().search(scope_id, query, limit=min(limit, 50))
    except MemoryUnavailableError as exc:
        return {"available": False, "warning": str(exc), "hits": [], "mode": None}
    return {
        "available": True,
        "mode": outcome.mode,
        "hits": [
            {
                "text": h.text,
                "score": h.score,
                "matched_by": h.matched_by,
                "entry_id": h.entry_id,
                "entry_version_id": h.entry_version_id,
            }
            for h in outcome.hits
        ],
    }


@router.post("/{session_id}/memories")
def write_memory(
    session_id: str,
    body: MemoryWriteRequest,
    authorization: str | None = Header(default=None),
) -> dict:
    require_session(session_id, authorization)
    return remember_for_session(session_id, body.kind, body.text)
