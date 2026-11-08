"""Study preferences endpoints (exam date, goal, language)."""

from __future__ import annotations

from fastapi import APIRouter, Header

from app.api.deps import remember_for_session, require_session
from app.api.schemas import PreferencesOut, PreferencesUpdate
from app.core.seekdb import get_engine

router = APIRouter(prefix="/api/sessions", tags=["preferences"])


@router.get("/{session_id}/preferences", response_model=PreferencesOut)
def get_preferences(
    session_id: str, authorization: str | None = Header(default=None)
) -> PreferencesOut:
    require_session(session_id, authorization)
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT exam_date, goal, preferred_language FROM user_preferences WHERE session_id=%s",
            (session_id,),
        )
        row = cur.fetchone()
    if row is None:
        return PreferencesOut(session_id=session_id)
    return PreferencesOut(
        session_id=session_id,
        exam_date=row[0],
        goal=row[1],
        preferred_language=str(row[2]),
    )


@router.put("/{session_id}/preferences", response_model=PreferencesOut)
def put_preferences(
    session_id: str,
    body: PreferencesUpdate,
    authorization: str | None = Header(default=None),
) -> PreferencesOut:
    require_session(session_id, authorization)
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO user_preferences (session_id, exam_date, goal, preferred_language) "
            "VALUES (%s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE exam_date = VALUES(exam_date), "
            "goal = VALUES(goal), preferred_language = VALUES(preferred_language), "
            "updated_at = NOW()",
            (session_id, body.exam_date, body.goal, body.preferred_language),
        )
    if body.goal:
        remember_for_session(session_id, "study_goal", f"学习目标：{body.goal}")
    if body.exam_date:
        remember_for_session(session_id, "exam_date", f"考试日期：{body.exam_date}")
    return PreferencesOut(
        session_id=session_id,
        exam_date=body.exam_date,
        goal=body.goal,
        preferred_language=body.preferred_language,
    )
