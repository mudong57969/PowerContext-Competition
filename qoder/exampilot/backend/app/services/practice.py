"""Practice sessions: question selection, submission, grading, history."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.seekdb import get_engine
from app.services.mastery import get_mastery, update_mastery, weakest_knowledge_points
from app.services.question_bank import ensure_question_bank
from app.services.review import rebuild_review_plan
from app.services.scoring import _parse_options as parse_options
from app.services.scoring import grade_question

MODES = {"mixed", "weak", "mistakes"}


@dataclass
class PracticeQuestion:
    id: int
    type: str
    stem: str
    options: list[dict]
    difficulty: int
    knowledge_points: list[str] = field(default_factory=list)


def _options_json(value: str | None) -> list[dict]:
    if not value:
        return []
    return [{"letter": letter, "text": text} for letter, text in parse_options(value)]


def _kp_names(cur, question_id: int) -> list[str]:
    cur.execute(
        "SELECT kp.name FROM question_knowledge_links qkl "
        "JOIN knowledge_points kp ON qkl.knowledge_point_id = kp.id "
        "WHERE qkl.question_id=%s ORDER BY kp.id",
        (question_id,),
    )
    return [str(row[0]) for row in cur.fetchall()]


def _kp_ids(cur, question_id: int) -> list[int]:
    cur.execute(
        "SELECT knowledge_point_id FROM question_knowledge_links WHERE question_id=%s",
        (question_id,),
    )
    return [int(row[0]) for row in cur.fetchall()]


def _load_questions(cur, question_ids: list[int]) -> list[dict]:
    if not question_ids:
        return []
    placeholders = ",".join(["%s"] * len(question_ids))
    cur.execute(
        "SELECT id, question_type, stem, options, difficulty FROM questions "
        "WHERE id IN (" + placeholders + ")",
        question_ids,
    )
    rows = {int(row[0]): row for row in cur.fetchall()}
    questions = [
        {
            "id": qid,
            "type": str(rows[qid][1]),
            "stem": str(rows[qid][2]),
            "options": _options_json(rows[qid][3]),
            "difficulty": int(rows[qid][4]),
            "knowledge_points": _kp_names(cur, qid),
        }
        for qid in question_ids
        if qid in rows
    ]
    return questions


def _resolve_course(
    cur, session_id: str, course_id: int | None
) -> tuple[int | None, str | None]:
    if course_id is not None:
        cur.execute(
            "SELECT id, name FROM courses WHERE id=%s AND session_id=%s",
            (course_id, session_id),
        )
        row = cur.fetchone()
        if row:
            return int(row[0]), str(row[1])
        return None, None
    cur.execute(
        "SELECT id, name FROM courses WHERE session_id=%s ORDER BY id LIMIT 1",
        (session_id,),
    )
    row = cur.fetchone()
    if row:
        return int(row[0]), str(row[1])
    return None, None


def _questions_for_kps(cur, course_id: int, kp_ids: list[int], count: int) -> list[int]:
    if not kp_ids:
        return []
    placeholders = ",".join(["%s"] * len(kp_ids))
    cur.execute(
        "SELECT q.id FROM questions q WHERE q.course_id=%s AND EXISTS ("
        "SELECT 1 FROM question_knowledge_links l "
        "WHERE l.question_id=q.id AND l.knowledge_point_id IN (" + placeholders + ")"
        ") ORDER BY RAND() LIMIT %s",
        (course_id, *kp_ids, count),
    )
    return [int(row[0]) for row in cur.fetchall()]


def start_practice(
    session_id: str,
    course_id: int | None,
    knowledge_point_ids: list[int],
    count: int,
    mode: str,
) -> dict:
    if mode not in MODES:
        raise ValueError(f"unknown practice mode: {mode}")
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        resolved_course_id, course_name = _resolve_course(cur, session_id, course_id)
        if resolved_course_id is None:
            raise ValueError(
                "session has no course yet; upload and classify materials first"
            )
        if knowledge_point_ids:
            placeholders = ",".join(["%s"] * len(knowledge_point_ids))
            cur.execute(
                "SELECT COUNT(*) FROM knowledge_points kp "
                "JOIN courses co ON kp.course_id = co.id "
                "WHERE kp.id IN (" + placeholders + ") AND co.session_id=%s",
                (*knowledge_point_ids, session_id),
            )
            if int(cur.fetchone()[0]) != len(set(knowledge_point_ids)):
                raise ValueError(
                    "one or more knowledge points do not belong to this session"
                )
        ensure_question_bank(session_id, resolved_course_id)
        selected: list[int] = []
        if knowledge_point_ids:
            selected = _questions_for_kps(
                cur, resolved_course_id, knowledge_point_ids, count
            )
        elif mode == "mistakes":
            cur.execute(
                "SELECT DISTINCT a.question_id FROM attempts a "
                "JOIN practice_sessions ps ON a.practice_session_id = ps.id "
                "WHERE ps.session_id=%s AND a.is_correct=0 "
                "ORDER BY a.id DESC LIMIT %s",
                (session_id, count),
            )
            selected = [int(row[0]) for row in cur.fetchall()]
        elif mode == "weak":
            weak_ids = [
                rec.knowledge_point_id
                for rec in weakest_knowledge_points(session_id, limit=5)
            ]
            selected = _questions_for_kps(cur, resolved_course_id, weak_ids, count)
        needed = count - len(selected)
        if needed > 0:
            if selected:
                placeholders = ",".join(["%s"] * len(selected))
                cur.execute(
                    "SELECT id FROM questions WHERE course_id=%s AND id NOT IN ("
                    + placeholders
                    + ") ORDER BY RAND() LIMIT %s",
                    (resolved_course_id, *selected, needed),
                )
            else:
                cur.execute(
                    "SELECT id FROM questions WHERE course_id=%s ORDER BY RAND() LIMIT %s",
                    (resolved_course_id, needed),
                )
            selected += [int(row[0]) for row in cur.fetchall()]
        questions = _load_questions(cur, selected[:count])
        cur.execute(
            "INSERT INTO practice_sessions (session_id, course_id, mode, total_questions) "
            "VALUES (%s, %s, %s, %s)",
            (session_id, resolved_course_id, mode, len(questions)),
        )
        practice_session_id = int(cur.lastrowid)
    return {
        "practice_session_id": practice_session_id,
        "course_id": resolved_course_id,
        "course_name": course_name,
        "mode": mode,
        "total": len(questions),
        "questions": questions,
    }


def submit_practice(
    session_id: str, practice_session_id: int, answers: list[tuple[int, str]]
) -> dict:
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT ps.session_id FROM practice_sessions ps WHERE ps.id=%s",
            (practice_session_id,),
        )
        row = cur.fetchone()
        if row is None or str(row[0]) != session_id:
            raise LookupError(f"practice session not found: {practice_session_id}")
        cur.execute(
            "SELECT COUNT(*) FROM attempts WHERE practice_session_id=%s",
            (practice_session_id,),
        )
        if cur.fetchone()[0] > 0:
            raise ValueError("practice session was already submitted")
        question_ids = [qid for qid, _ in answers]
        placeholders = ",".join(["%s"] * len(question_ids))
        # Only questions that belong to this session may be graded (the
        # response echoes stem/answer/explanation, so foreign ids would leak).
        cur.execute(
            "SELECT COUNT(*) FROM questions q LEFT JOIN courses co ON q.course_id = co.id "
            "WHERE q.id IN (" + placeholders + ") "
            "AND (q.session_id=%s OR co.session_id=%s)",
            (*question_ids, session_id, session_id),
        )
        if int(cur.fetchone()[0]) != len(set(question_ids)):
            raise LookupError("one or more questions do not belong to this session")
        cur.execute(
            "SELECT id, question_type, answer, options, stem, explanation FROM questions "
            "WHERE id IN (" + placeholders + ")",
            question_ids,
        )
        qrows = {int(r[0]): r for r in cur.fetchall()}
        kp_results: dict[int, bool] = {}
        results: list[dict] = []
        correct_count = 0
        for qid, user_answer in answers:
            row = qrows.get(qid)
            if row is None:
                continue
            graded = grade_question(str(row[1]), str(row[2]), row[3], user_answer)
            if graded.is_correct:
                correct_count += 1
            for kp_id in _kp_ids(cur, qid):
                kp_results[kp_id] = kp_results.get(kp_id, True) and graded.is_correct
            cur.execute(
                "INSERT INTO attempts (practice_session_id, question_id, user_answer, "
                "is_correct, score, grading_evidence) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    practice_session_id,
                    qid,
                    user_answer,
                    1 if graded.is_correct else 0,
                    graded.score,
                    graded.evidence,
                ),
            )
            results.append(
                {
                    "question_id": qid,
                    "type": str(row[1]),
                    "stem": str(row[4]),
                    "options": _options_json(row[3]),
                    "user_answer": user_answer,
                    "is_correct": graded.is_correct,
                    "score": graded.score,
                    "evidence": graded.evidence,
                    "correct_answer": str(row[2]),
                    "explanation": str(row[5]),
                    "knowledge_points": _kp_names(cur, qid),
                }
            )
        total = len(results)
        score = round(100.0 * correct_count / total, 1) if total else 0.0
        cur.execute(
            "UPDATE practice_sessions SET correct_count=%s, score=%s, finished_at=NOW() "
            "WHERE id=%s",
            (correct_count, score, practice_session_id),
        )
    update_mastery(session_id, kp_results)
    review_created = rebuild_review_plan(session_id)
    mastery_snapshot = [
        {
            "knowledge_point_id": rec.knowledge_point_id,
            "name": rec.name,
            "mastery_score": rec.mastery_score,
            "practice_count": rec.practice_count,
            "correct_count": rec.correct_count,
            "streak": rec.streak,
        }
        for rec in get_mastery(session_id)
    ]
    return {
        "practice_session_id": practice_session_id,
        "total": total,
        "correct_count": correct_count,
        "score": score,
        "results": results,
        "mastery": mastery_snapshot,
        "review_tasks_created": review_created,
    }


def practice_history(session_id: str) -> list[dict]:
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT ps.id, ps.course_id, co.name, ps.mode, ps.total_questions, "
            "ps.correct_count, ps.score, ps.started_at, ps.finished_at "
            "FROM practice_sessions ps "
            "LEFT JOIN courses co ON ps.course_id = co.id "
            "WHERE ps.session_id=%s ORDER BY ps.id DESC",
            (session_id,),
        )
        return [
            {
                "id": int(row[0]),
                "course_id": row[1],
                "course_name": str(row[2]) if row[2] else None,
                "mode": str(row[3]),
                "total_questions": int(row[4]),
                "correct_count": int(row[5]),
                "score": float(row[6]) if row[6] is not None else None,
                "started_at": row[7],
                "finished_at": row[8],
            }
            for row in cur.fetchall()
        ]


def practice_result(session_id: str, practice_session_id: int) -> dict:
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT ps.id, ps.course_id, co.name, ps.mode, ps.total_questions, "
            "ps.correct_count, ps.score, ps.started_at, ps.finished_at "
            "FROM practice_sessions ps "
            "LEFT JOIN courses co ON ps.course_id = co.id "
            "WHERE ps.id=%s AND ps.session_id=%s",
            (practice_session_id, session_id),
        )
        row = cur.fetchone()
        if row is None:
            return {}
        summary = {
            "id": int(row[0]),
            "course_id": row[1],
            "course_name": str(row[2]) if row[2] else None,
            "mode": str(row[3]),
            "total_questions": int(row[4]),
            "correct_count": int(row[5]),
            "score": float(row[6]) if row[6] is not None else None,
            "started_at": row[7],
            "finished_at": row[8],
        }
        cur.execute(
            "SELECT a.question_id, a.user_answer, a.is_correct, a.score, a.grading_evidence, "
            "q.question_type, q.stem, q.options, q.answer, q.explanation "
            "FROM attempts a JOIN questions q ON a.question_id = q.id "
            "WHERE a.practice_session_id=%s ORDER BY a.id",
            (practice_session_id,),
        )
        attempts = [
            {
                "question_id": int(r[0]),
                "user_answer": str(r[1]),
                "is_correct": bool(r[2]),
                "score": float(r[3]) if r[3] is not None else None,
                "evidence": str(r[4]),
                "type": str(r[5]),
                "stem": str(r[6]),
                "options": _options_json(r[7]),
                "correct_answer": str(r[8]),
                "explanation": str(r[9]),
                "knowledge_points": _kp_names(cur, int(r[0])),
            }
            for r in cur.fetchall()
        ]
        summary["attempts"] = attempts
    return summary


def list_mistakes(session_id: str) -> list[dict]:
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT a.question_id, q.question_type, q.stem, q.options, q.answer, "
            "q.explanation, a.user_answer, a.created_at "
            "FROM attempts a "
            "JOIN practice_sessions ps ON a.practice_session_id = ps.id "
            "JOIN questions q ON a.question_id = q.id "
            "WHERE ps.session_id=%s AND a.is_correct=0 "
            "ORDER BY a.created_at DESC",
            (session_id,),
        )
        rows = cur.fetchall()
        grouped: dict[int, dict] = {}
        for row in rows:
            qid = int(row[0])
            entry = grouped.get(qid)
            if entry is None:
                entry = grouped[qid] = {
                    "question_id": qid,
                    "type": str(row[1]),
                    "stem": str(row[2]),
                    "options": _options_json(row[3]),
                    "correct_answer": str(row[4]),
                    "explanation": str(row[5]),
                    "knowledge_points": _kp_names(cur, qid),
                    "wrong_count": 0,
                    "last_wrong_at": row[7],
                    "user_answers": [],
                }
            entry["wrong_count"] += 1
            entry["user_answers"].append(str(row[6]))
    return list(grouped.values())
