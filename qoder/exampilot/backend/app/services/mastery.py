"""Knowledge-point mastery tracking.

Mastery is a deterministic function of real practice outcomes:

    accuracy = correct_count / practice_count
    mastery_score = 0.75 * accuracy + 0.25 * min(streak, 5) / 5

The streak counts consecutive correct answers and resets on a wrong one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core.seekdb import get_engine


@dataclass
class MasteryRecord:
    knowledge_point_id: int
    name: str
    course_id: int | None
    course_name: str | None
    chapter_name: str | None
    practice_count: int
    correct_count: int
    streak: int
    mastery_score: float
    last_practiced_at: datetime | None


def compute_mastery(correct_count: int, practice_count: int, streak: int) -> float:
    if practice_count <= 0:
        return 0.0
    return round(
        0.75 * (correct_count / practice_count) + 0.25 * min(streak, 5) / 5.0, 3
    )


def update_mastery(session_id: str, results: dict[int, bool]) -> None:
    """Upsert practice outcomes per knowledge point."""
    if not results:
        return
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        placeholders = ",".join(["%s"] * len(results))
        cur.execute(
            "SELECT knowledge_point_id, practice_count, correct_count, streak "
            "FROM knowledge_mastery WHERE session_id=%s AND knowledge_point_id IN ("
            + placeholders
            + ")",
            (session_id, *results.keys()),
        )
        existing = {row[0]: (row[1], row[2], row[3]) for row in cur.fetchall()}
        for kp_id, correct in results.items():
            count, ok_count, streak = existing.get(kp_id, (0, 0, 0))
            count += 1
            if correct:
                ok_count += 1
                streak += 1
            else:
                streak = 0
            mastery = compute_mastery(ok_count, count, streak)
            cur.execute(
                """
                INSERT INTO knowledge_mastery
                    (session_id, knowledge_point_id, practice_count, correct_count,
                     streak, last_practiced_at, mastery_score)
                VALUES (%s, %s, %s, %s, %s, NOW(), %s)
                ON DUPLICATE KEY UPDATE
                    practice_count = VALUES(practice_count),
                    correct_count = VALUES(correct_count),
                    streak = VALUES(streak),
                    last_practiced_at = NOW(),
                    mastery_score = VALUES(mastery_score)
                """,
                (session_id, kp_id, count, ok_count, streak, mastery),
            )


_MASTERY_SELECT = """
    SELECT km.knowledge_point_id, kp.name, kp.course_id, co.name, ch.name,
           km.practice_count, km.correct_count, km.streak,
           km.mastery_score, km.last_practiced_at
    FROM knowledge_mastery km
    JOIN knowledge_points kp ON km.knowledge_point_id = kp.id
    LEFT JOIN courses co ON kp.course_id = co.id
    LEFT JOIN chapters ch ON kp.chapter_id = ch.id
    WHERE km.session_id=%s
"""


def _rows_to_records(rows: list) -> list[MasteryRecord]:
    return [
        MasteryRecord(
            knowledge_point_id=row[0],
            name=row[1],
            course_id=row[2],
            course_name=row[3],
            chapter_name=row[4],
            practice_count=row[5],
            correct_count=row[6],
            streak=row[7],
            mastery_score=float(row[8]),
            last_practiced_at=row[9],
        )
        for row in rows
    ]


def get_mastery(session_id: str, course_id: int | None = None) -> list[MasteryRecord]:
    sql = _MASTERY_SELECT
    params: list = [session_id]
    if course_id is not None:
        sql += " AND kp.course_id=%s"
        params.append(course_id)
    sql += " ORDER BY km.mastery_score ASC, km.practice_count ASC"
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        return _rows_to_records(cur.fetchall())


def weakest_knowledge_points(session_id: str, limit: int = 5) -> list[MasteryRecord]:
    sql = (
        _MASTERY_SELECT
        + " ORDER BY km.mastery_score ASC, km.practice_count ASC LIMIT %s"
    )
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(sql, (session_id, limit))
        return _rows_to_records(cur.fetchall())
