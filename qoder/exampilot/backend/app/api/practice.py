"""Practice endpoints: start, submit, history, results."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from app.api.deps import (
    authenticate,
    remember_for_session,
    require_owned_session,
    require_session,
)
from app.api.schemas import (
    GradedAnswerOut,
    PracticeQuestionOut,
    PracticeStartRequest,
    PracticeStartResponse,
    SubmitRequest,
    SubmitResponse,
)
from app.services.practice import (
    practice_history,
    practice_result,
    start_practice,
    submit_practice,
)

router = APIRouter(prefix="/api", tags=["practice"])


def _practice_session_owner(practice_session_id: int) -> str:
    from app.core.seekdb import get_engine

    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT session_id FROM practice_sessions WHERE id=%s",
            (practice_session_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"practice session not found: {practice_session_id}"
        )
    return str(row[0])


@router.post(
    "/sessions/{session_id}/practice/start", response_model=PracticeStartResponse
)
def start(
    session_id: str,
    body: PracticeStartRequest,
    authorization: str | None = Header(default=None),
) -> PracticeStartResponse:
    require_session(session_id, authorization)
    try:
        outcome = start_practice(
            session_id,
            body.course_id,
            body.knowledge_point_ids,
            body.count,
            body.mode,
        )
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


@router.post("/practice/{practice_session_id}/submit", response_model=SubmitResponse)
def submit(
    practice_session_id: int,
    body: SubmitRequest,
    authorization: str | None = Header(default=None),
) -> SubmitResponse:
    identity_session = authenticate(authorization)
    session_id = _practice_session_owner(practice_session_id)
    require_owned_session(identity_session, session_id)
    try:
        outcome = submit_practice(
            session_id,
            practice_session_id,
            [(a.question_id, a.answer) for a in body.answers],
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    summary = (
        f"完成练习 {outcome['total']} 题，答对 {outcome['correct_count']} 题，"
        f"得分 {outcome['score']}；涉及知识点 {len(outcome['mastery'])} 个。"
    )
    memory = remember_for_session(session_id, "practice_result", summary)
    wrong_kps = [m["name"] for m in outcome["mastery"] if m["mastery_score"] < 0.6]
    if wrong_kps:
        remember_for_session(
            session_id,
            "weak_knowledge_points",
            "薄弱知识点：" + "、".join(wrong_kps[:5]),
        )
    return SubmitResponse(
        practice_session_id=practice_session_id,
        total=outcome["total"],
        correct_count=outcome["correct_count"],
        score=outcome["score"],
        results=[
            GradedAnswerOut(
                question_id=r["question_id"],
                type=r["type"],
                stem=r["stem"],
                options=r["options"],
                user_answer=r["user_answer"],
                is_correct=r["is_correct"],
                score=r["score"],
                evidence=r["evidence"],
                correct_answer=r["correct_answer"],
                explanation=r["explanation"],
                knowledge_points=r["knowledge_points"],
            )
            for r in outcome["results"]
        ],
        mastery=outcome["mastery"],
        review_tasks_created=outcome["review_tasks_created"],
        memory=memory,
    )


@router.get("/sessions/{session_id}/practice/history")
def history(
    session_id: str, authorization: str | None = Header(default=None)
) -> list[dict]:
    require_session(session_id, authorization)
    return practice_history(session_id)


@router.get("/practice/{practice_session_id}")
def result(
    practice_session_id: int, authorization: str | None = Header(default=None)
) -> dict:
    identity_session = authenticate(authorization)
    session_id = _practice_session_owner(practice_session_id)
    require_owned_session(identity_session, session_id)
    data = practice_result(session_id, practice_session_id)
    if not data:
        raise HTTPException(
            status_code=404, detail=f"practice session not found: {practice_session_id}"
        )
    return data
