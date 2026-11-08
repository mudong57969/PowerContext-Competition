"""Hybrid knowledge search with PowerContext memory recall."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from app.api.deps import (
    get_embedding_provider,
    get_memory_service,
    require_session,
    session_scope_id,
)
from app.api.schemas import MemoryRecallOut, SearchRequest, SearchResponse, SourceHitOut
from app.core.seekdb import get_engine
from app.memory.powercontext import MemoryUnavailableError
from app.retrieval.hybrid import hybrid_search

router = APIRouter(prefix="/api/sessions", tags=["search"])


def _assert_owned_filter(
    session_id: str, course_id: int | None, chapter_id: int | None
) -> None:
    """Nested filters must reference resources owned by this session."""
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        if course_id is not None:
            cur.execute(
                "SELECT id FROM courses WHERE id=%s AND session_id=%s",
                (course_id, session_id),
            )
            if cur.fetchone() is None:
                raise HTTPException(
                    status_code=404, detail=f"course not found: {course_id}"
                )
        if chapter_id is not None:
            cur.execute(
                "SELECT ch.id FROM chapters ch JOIN courses co ON ch.course_id=co.id "
                "WHERE ch.id=%s AND co.session_id=%s",
                (chapter_id, session_id),
            )
            if cur.fetchone() is None:
                raise HTTPException(
                    status_code=404, detail=f"chapter not found: {chapter_id}"
                )


@router.post("/{session_id}/search", response_model=SearchResponse)
def search(
    session_id: str,
    body: SearchRequest,
    authorization: str | None = Header(default=None),
) -> SearchResponse:
    require_session(session_id, authorization)
    _assert_owned_filter(session_id, body.course_id, body.chapter_id)
    result = hybrid_search(
        session_id,
        body.query,
        get_embedding_provider(),
        course_id=body.course_id,
        chapter_id=body.chapter_id,
        limit=body.limit,
    )
    hits = [
        SourceHitOut(
            chunk_id=h.chunk_id,
            document_id=h.document_id,
            filename=h.filename,
            course=h.course,
            chapter=h.chapter,
            page_number=h.page_number,
            text=h.text,
            score=h.score,
            matched_by=h.matched_by,
        )
        for h in result.hits
    ]
    memory = MemoryRecallOut(available=False)
    scope_id = session_scope_id(session_id)
    if scope_id:
        try:
            outcome = get_memory_service().search(scope_id, body.query, limit=5)
            memory = MemoryRecallOut(
                available=True,
                mode=outcome.mode,
                hits=[
                    {
                        "text": h.text,
                        "score": h.score,
                        "matched_by": h.matched_by,
                        "entry_id": h.entry_id,
                    }
                    for h in outcome.hits
                ],
            )
        except MemoryUnavailableError as exc:
            memory = MemoryRecallOut(available=False, warning=str(exc))
    else:
        memory = MemoryRecallOut(
            available=False, warning="session has no PowerContext scope"
        )
    return SearchResponse(
        query=body.query,
        hits=hits,
        mode=result.mode,
        fts_hits=result.fts_hits,
        vector_hits=result.vector_hits,
        warning=result.warning,
        memory=memory,
    )
