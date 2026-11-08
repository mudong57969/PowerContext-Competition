"""Mistake book endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from app.api.deps import require_session
from app.api.schemas import (
    MistakeOut,
    PracticeQuestionOut,
    PracticeStartRequest,
    PracticeStartResponse,
)
from app.services.practice import list_mistakes, start_practice

router = APIRouter(prefix="/api/sessions", tags=["mistakes"])


@router.get("/{session_id}/mistakes", response_model=list[MistakeOut])
def mistakes(
    session_id: str, authorization: str | None = Header(default=None)
) -> list[MistakeOut]:
    require_session(session_id, authorization)
    return [
        MistakeOut(
            question_id=m["question_id"],
            type=m["type"],
            stem=m["stem"],
            options=m["options"],
            correct_answer=m["correct_answer"],
            explanation=m["explanation"],
            knowledge_points=m["knowledge_points"],
            wrong_count=m["wrong_count"],
            last_wrong_at=m["last_wrong_at"],
            user_answers=m["user_answers"],
        )
        for m in list_mistakes(session_id)
    ]


@router.post("/{session_id}/mistakes/practice", response_model=PracticeStartResponse)
def practice_from_mistakes(
    session_id: str,
    body: PracticeStartRequest | None = None,
    authorization: str | None = Header(default=None),
) -> PracticeStartResponse:
    require_session(session_id, authorization)
    count = body.count if body else 5
    try:
        outcome = start_practice(session_id, None, [], count, "mistakes")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PracticeStartResponse(
        practice_session_id=outcome["practice_session_id"],
        course_id=outcome["course_id"],
        course_name=outcome["course_name"],
        mode=outcome["mode"],
        total=outcome["total"],
        questions=[
            PracticeQuestionOut(
                id=q["id"],
                type=q["type"],
                stem=q["stem"],
                options=q["options"],
                difficulty=q["difficulty"],
                knowledge_points=q["knowledge_points"],
            )
            for q in outcome["questions"]
        ],
    )
