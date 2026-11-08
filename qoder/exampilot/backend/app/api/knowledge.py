"""Course / knowledge-point / mastery listing endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Header

from app.api.deps import require_session
from app.api.schemas import CourseOut, KnowledgePointOut
from app.core.seekdb import get_engine
from app.services.mastery import get_mastery

router = APIRouter(prefix="/api/sessions", tags=["knowledge"])


@router.get("/{session_id}/courses", response_model=list[CourseOut])
def list_courses(
    session_id: str, authorization: str | None = Header(default=None)
) -> list[CourseOut]:
    require_session(session_id, authorization)
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT c.id, c.name, c.status, c.confidence, "
            "(SELECT COUNT(*) FROM chapters ch WHERE ch.course_id = c.id), "
            "(SELECT COUNT(*) FROM knowledge_points kp WHERE kp.course_id = c.id), "
            "(SELECT COUNT(*) FROM documents d WHERE d.course_id = c.id), "
            "(SELECT COUNT(*) FROM questions q WHERE q.course_id = c.id) "
            "FROM courses c WHERE c.session_id=%s ORDER BY c.id",
            (session_id,),
        )
        return [
            CourseOut(
                id=int(row[0]),
                name=str(row[1]),
                status=str(row[2]),
                confidence=float(row[3]),
                chapter_count=int(row[4]),
                knowledge_point_count=int(row[5]),
                document_count=int(row[6]),
                question_count=int(row[7]),
            )
            for row in cur.fetchall()
        ]


@router.get("/{session_id}/knowledge-points", response_model=list[KnowledgePointOut])
def list_knowledge_points(
    session_id: str,
    course_id: int | None = None,
    authorization: str | None = Header(default=None),
) -> list[KnowledgePointOut]:
    require_session(session_id, authorization)
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        sql = (
            "SELECT kp.id, kp.name, kp.course_id, co.name, ch.name, kp.description "
            "FROM knowledge_points kp "
            "JOIN courses co ON kp.course_id = co.id "
            "LEFT JOIN chapters ch ON kp.chapter_id = ch.id "
            "WHERE co.session_id=%s"
        )
        params: list = [session_id]
        if course_id is not None:
            sql += " AND kp.course_id=%s"
            params.append(course_id)
        sql += " ORDER BY kp.course_id, kp.id"
        cur.execute(sql, params)
        rows = cur.fetchall()
    mastery = {
        rec.knowledge_point_id: rec for rec in get_mastery(session_id, course_id)
    }
    return [
        KnowledgePointOut(
            id=int(row[0]),
            name=str(row[1]),
            course_id=int(row[2]),
            course_name=str(row[3]) if row[3] else None,
            chapter_name=str(row[4]) if row[4] else None,
            description=str(row[5]) if row[5] else None,
            mastery=(
                {
                    "practice_count": mastery[row[0]].practice_count,
                    "correct_count": mastery[row[0]].correct_count,
                    "streak": mastery[row[0]].streak,
                    "mastery_score": mastery[row[0]].mastery_score,
                }
                if int(row[0]) in mastery
                else None
            ),
        )
        for row in rows
    ]


@router.get("/{session_id}/mastery")
def list_mastery(
    session_id: str,
    course_id: int | None = None,
    authorization: str | None = Header(default=None),
) -> list[dict]:
    require_session(session_id, authorization)
    return [
        {
            "knowledge_point_id": rec.knowledge_point_id,
            "name": rec.name,
            "course_id": rec.course_id,
            "course_name": rec.course_name,
            "chapter_name": rec.chapter_name,
            "practice_count": rec.practice_count,
            "correct_count": rec.correct_count,
            "streak": rec.streak,
            "mastery_score": rec.mastery_score,
            "last_practiced_at": rec.last_practiced_at,
        }
        for rec in get_mastery(session_id, course_id)
    ]
