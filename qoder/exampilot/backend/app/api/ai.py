"""AI explanation endpoint (retrieval-augmented, memory-aware)."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from app.api.deps import (
    get_embedding_provider,
    get_llm_provider,
    remember_for_session,
    require_session,
)
from app.api.schemas import ExplainRequest, ExplainResponse, SourceHitOut
from app.core.seekdb import get_engine
from app.retrieval.hybrid import hybrid_search
from app.services.llm import ExplanationError

router = APIRouter(prefix="/api/sessions", tags=["ai"])


@router.post("/{session_id}/explain", response_model=ExplainResponse)
def explain(
    session_id: str,
    body: ExplainRequest,
    authorization: str | None = Header(default=None),
) -> ExplainResponse:
    require_session(session_id, authorization)
    eng = get_engine()
    kp_name: str | None = None
    course_id: int | None = None
    if body.knowledge_point_id is not None:
        with eng.connect() as conn:
            cur = conn.cursor()
            # The knowledge point must belong to a course owned by this session.
            cur.execute(
                "SELECT kp.name, kp.course_id FROM knowledge_points kp "
                "JOIN courses co ON kp.course_id = co.id "
                "WHERE kp.id=%s AND co.session_id=%s",
                (body.knowledge_point_id, session_id),
            )
            row = cur.fetchone()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"knowledge point not found: {body.knowledge_point_id}",
            )
        kp_name = str(row[0])
        course_id = int(row[1])
    query = kp_name or body.query
    if not query:
        raise HTTPException(
            status_code=400, detail="knowledge_point_id or query is required"
        )
    search_result = hybrid_search(
        session_id,
        query,
        get_embedding_provider(),
        course_id=course_id,
        limit=5,
    )
    chunk_dicts = [
        {
            "filename": h.filename,
            "page_number": h.page_number,
            "text": h.text,
            "course": h.course,
            "chapter": h.chapter,
        }
        for h in search_result.hits
    ]
    try:
        explanation = get_llm_provider().explain(
            knowledge_point=query,
            context_chunks=chunk_dicts,
            question_stem=body.question_stem,
        )
    except ExplanationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    memory = remember_for_session(
        session_id,
        "explain",
        f"请求讲解知识点「{query}」，命中 {len(chunk_dicts)} 条资料片段；讲解由 {explanation.provider} 生成。",
    )
    return ExplainResponse(
        knowledge_point=query,
        explanation=explanation.text,
        provider=explanation.provider,
        sources=[
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
            for h in search_result.hits
        ],
        memory=memory,
    )
