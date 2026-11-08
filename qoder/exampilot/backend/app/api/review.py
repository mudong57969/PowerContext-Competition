"""Review plan endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from app.api.deps import authenticate, require_owned_session, require_session
from app.api.schemas import (
    ReviewCompleteRequest,
    ReviewCompleteResponse,
    ReviewPlanResponse,
    ReviewTaskOut,
)
from app.core.seekdb import get_engine
from app.services.mastery import get_mastery
from app.services.review import complete_review, list_reviews

router = APIRouter(prefix="/api", tags=["review"])


@router.get("/sessions/{session_id}/review/plan", response_model=ReviewPlanResponse)
def review_plan(
    session_id: str, authorization: str | None = Header(default=None)
) -> ReviewPlanResponse:
    require_session(session_id, authorization)
    due = list_reviews(session_id, due_only=True)
    upcoming = list_reviews(session_id, due_only=False)
    mastery = [
        {
            "knowledge_point_id": rec.knowledge_point_id,
            "name": rec.name,
            "mastery_score": rec.mastery_score,
            "practice_count": rec.practice_count,
            "streak": rec.streak,
        }
        for rec in get_mastery(session_id)
    ]
    return ReviewPlanResponse(
        due=[_task_out(t) for t in due],
        upcoming=[_task_out(t) for t in upcoming],
        mastery=mastery,
    )


def _task_out(task) -> ReviewTaskOut:
    return ReviewTaskOut(
        id=task.id,
        knowledge_point_id=task.knowledge_point_id,
        knowledge_point_name=task.knowledge_point_name,
        course_name=task.course_name,
        due_date=task.due_date,
        reason=task.reason,
        status=task.status,
        mastery_score=task.mastery_score,
    )


@router.post("/review-tasks/{task_id}/complete", response_model=ReviewCompleteResponse)
def complete(
    task_id: int,
    body: ReviewCompleteRequest,
    authorization: str | None = Header(default=None),
) -> ReviewCompleteResponse:
    identity_session = authenticate(authorization)
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT session_id FROM review_tasks WHERE id=%s", (task_id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(
                status_code=404, detail=f"review task not found: {task_id}"
            )
        session_id = str(row[0])
    require_owned_session(identity_session, session_id)
    outcome = complete_review(session_id, task_id, body.correct)
    if outcome["status"] == "not_found":
        raise HTTPException(status_code=404, detail=f"review task not found: {task_id}")
    return ReviewCompleteResponse(
        task_id=outcome["task_id"],
        status=outcome["status"],
        follow_up_task_id=outcome["follow_up_task_id"],
    )
