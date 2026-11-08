"""Spaced-repetition review planning driven by real mastery data.

Intervals follow the review streak: [1, 3, 7, 14, 30] days. A knowledge point
stays in the plan while its mastery is below the threshold or it has too few
practices; answering a review incorrectly schedules a follow-up for the next
day.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.core.seekdb import get_engine

INTERVALS_DAYS = [1, 3, 7, 14, 30]
MASTERY_REVIEW_THRESHOLD = 0.6
MIN_PRACTICES_BEFORE_SKIP = 3


@dataclass
class ReviewTask:
    id: int
    knowledge_point_id: int
    knowledge_point_name: str
    course_name: str | None
    due_date: date | None
    reason: str
    status: str
    mastery_score: float | None


def review_interval_days(streak: int) -> int:
    return INTERVALS_DAYS[min(streak, len(INTERVALS_DAYS) - 1)]


def needs_review(practice_count: int, mastery_score: float) -> bool:
    return not (
        practice_count >= MIN_PRACTICES_BEFORE_SKIP
        and mastery_score >= MASTERY_REVIEW_THRESHOLD
    )


def rebuild_review_plan(session_id: str, today: date | None = None) -> int:
    """Create pending review tasks for weak knowledge points (idempotent)."""
    from app.services.mastery import get_mastery

    today = today or date.today()
    created = 0
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        for rec in get_mastery(session_id):
            cur.execute(
                "SELECT COUNT(*) FROM review_tasks "
                "WHERE session_id=%s AND knowledge_point_id=%s AND status='pending'",
                (session_id, rec.knowledge_point_id),
            )
            if cur.fetchone()[0]:
                continue
            if not needs_review(rec.practice_count, rec.mastery_score):
                continue
            interval = review_interval_days(rec.streak)
            due = today + timedelta(days=interval)
            reason = (
                f"mastery={rec.mastery_score:.2f} (threshold {MASTERY_REVIEW_THRESHOLD}), "
                f"practices={rec.practice_count}, streak={rec.streak} → due in {interval}d"
            )
            cur.execute(
                "INSERT INTO review_tasks "
                "(session_id, knowledge_point_id, due_date, reason, status) "
                "VALUES (%s, %s, %s, %s, 'pending')",
                (session_id, rec.knowledge_point_id, due, reason),
            )
            created += 1
    return created


def list_reviews(
    session_id: str, *, due_only: bool = False, limit: int = 50
) -> list[ReviewTask]:
    sql = """
        SELECT rt.id, rt.knowledge_point_id, kp.name, co.name,
               rt.due_date, rt.reason, rt.status, km.mastery_score
        FROM review_tasks rt
        LEFT JOIN knowledge_points kp ON rt.knowledge_point_id = kp.id
        LEFT JOIN courses co ON kp.course_id = co.id
        LEFT JOIN knowledge_mastery km
            ON km.session_id = rt.session_id AND km.knowledge_point_id = rt.knowledge_point_id
        WHERE rt.session_id=%s AND rt.status='pending'
    """
    params: list = [session_id]
    if due_only:
        sql += " AND rt.due_date <= CURDATE()"
    sql += " ORDER BY rt.due_date ASC LIMIT %s"
    params.append(limit)
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        return [
            ReviewTask(
                id=row[0],
                knowledge_point_id=row[1],
                knowledge_point_name=row[2],
                course_name=row[3],
                due_date=row[4],
                reason=row[5],
                status=row[6],
                mastery_score=float(row[7]) if row[7] is not None else None,
            )
            for row in cur.fetchall()
        ]


def complete_review(session_id: str, task_id: int, correct: bool) -> dict:
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT knowledge_point_id FROM review_tasks WHERE id=%s AND session_id=%s",
            (task_id, session_id),
        )
        row = cur.fetchone()
        if not row:
            return {"task_id": task_id, "status": "not_found"}
        kp_id = row[0]
        cur.execute(
            "UPDATE review_tasks SET status='completed', completed_at=NOW() WHERE id=%s",
            (task_id,),
        )
        follow_up_id = None
        if not correct:
            cur.execute(
                "INSERT INTO review_tasks "
                "(session_id, knowledge_point_id, due_date, reason, status) "
                "VALUES (%s, %s, CURDATE() + INTERVAL 1 DAY, %s, 'pending')",
                (session_id, kp_id, "previous review answered incorrectly"),
            )
            follow_up_id = cur.lastrowid
    return {
        "task_id": task_id,
        "status": "completed",
        "follow_up_task_id": follow_up_id,
    }
