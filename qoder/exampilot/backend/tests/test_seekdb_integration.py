"""Integration tests against the real embedded seekdb engine (Linux/macOS only).

On Windows these tests are skipped; run the suite inside WSL2 to exercise the
actual OceanBase-compatible engine (FULLTEXT, VECTOR, upserts).
"""

import os
import shutil
import tempfile

import pytest

_AVAILABLE = os.name == "posix"
if _AVAILABLE:
    try:
        import pylibseekdb  # noqa: F401
    except Exception:  # pragma: no cover  # noqa: BLE001 - optional native module probe
        _AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _AVAILABLE,
    reason="seekdb embedded engine requires Linux/macOS with pylibseekdb",
)


@pytest.fixture(scope="module")
def engine():
    from app.core.seekdb import configure
    from app.models.schema import create_all_tables

    # Unix sockets do not work on drvfs mounts, so tests always use /tmp.
    data_dir = tempfile.mkdtemp(prefix="exampilot-test-seekdb-")
    eng = configure(data_dir)
    create_all_tables()
    yield eng
    eng.close()
    shutil.rmtree(data_dir, ignore_errors=True)


def _exec(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur


def _seed_document(session_id: str, course_name: str = "数字集成电路"):
    from app.core.seekdb import get_engine
    from app.retrieval.fts_text import fts_tokenize

    eng = get_engine()
    with eng.connect() as conn:
        cur = _exec(
            conn,
            "INSERT INTO demo_sessions (id, name) VALUES (%s, %s)",
            (session_id, session_id),
        )
        cur.execute(
            "INSERT INTO courses (session_id, name, confidence, status) VALUES (%s, %s, 0.9, 'auto')",
            (session_id, course_name),
        )
        course_id = cur.lastrowid
        cur.execute(
            "INSERT INTO documents (session_id, course_id, filename, file_type, file_hash, file_size) "
            "VALUES (%s, %s, 'cmos_notes.md', 'md', 'hash', 100)",
            (session_id, course_id),
        )
        doc_id = cur.lastrowid
        texts = [
            "### 动态功耗 动态功耗 P = alpha * CL * VDD^2 * f，其中 alpha 是开关活动因子。",
            "### 泄漏功耗 阈值电压降低时亚阈值泄漏电流指数增大。",
        ]
        for idx, text in enumerate(texts):
            cur.execute(
                "INSERT INTO document_chunks "
                "(document_id, course_id, chunk_index, page_number, original_text, normalized_text, fts_text) "
                "VALUES (%s, %s, %s, 1, %s, %s, %s)",
                (doc_id, course_id, idx, text, text, fts_tokenize(text)),
            )
        return course_id


def test_schema_tables_created(engine):
    from app.core.seekdb import get_engine

    with get_engine().connect() as conn:
        cur = _exec(conn, "SHOW TABLES")
        tables = {row[0] for row in cur.fetchall()}
    for expected in (
        "document_chunks",
        "questions",
        "knowledge_mastery",
        "review_tasks",
        "memory_events",
    ):
        assert expected in tables


def test_fts_trigram_matches_chinese(engine):
    from app.core.seekdb import get_engine
    from app.retrieval.fts_text import fts_tokenize

    _seed_document("fts-session")
    with get_engine().connect() as conn:
        cur = _exec(
            conn,
            "SELECT id FROM document_chunks WHERE MATCH(fts_text) AGAINST (%s)",
            (fts_tokenize("动态功耗公式"),),
        )
        ids = [row[0] for row in cur.fetchall()]
        assert ids, "trigram-expanded Chinese query must hit FTS"
        # the leakage chunk must NOT match the dynamic-power query
        cur.execute(
            "SELECT dc.id FROM document_chunks dc JOIN documents d ON dc.document_id=d.id "
            "WHERE d.session_id='fts-session' AND MATCH(dc.fts_text) AGAINST (%s)",
            (fts_tokenize("泄漏功耗 亚阈值"),),
        )
        assert len(cur.fetchall()) == 1


def test_hybrid_search_fts_only_mode(engine):
    from app.retrieval.hybrid import hybrid_search

    _seed_document("hybrid-session")
    result = hybrid_search("hybrid-session", "动态功耗公式", None, limit=5)
    assert result.mode == "fts-only"
    assert result.fts_hits >= 1
    assert result.vector_hits == 0
    assert result.hits[0].matched_by == ["fts"]
    assert result.hits[0].filename == "cmos_notes.md"


def test_mastery_review_flow(engine):
    from app.core.seekdb import get_engine
    from app.services.mastery import get_mastery, update_mastery
    from app.services.review import complete_review, list_reviews, rebuild_review_plan

    session_id = "mastery-session"
    course_id = _seed_document(session_id)
    with get_engine().connect() as conn:
        cur = _exec(
            conn,
            "INSERT INTO knowledge_points (course_id, chapter_id, name) VALUES (%s, NULL, '动态功耗')",
            (course_id,),
        )
        kp_id = cur.lastrowid

    update_mastery(session_id, {kp_id: False})
    update_mastery(session_id, {kp_id: True})
    update_mastery(session_id, {kp_id: False})

    records = get_mastery(session_id)
    assert len(records) == 1
    rec = records[0]
    assert rec.practice_count == 3
    assert rec.correct_count == 1
    assert rec.streak == 0
    assert rec.mastery_score == pytest.approx(0.25, abs=1e-3)

    created = rebuild_review_plan(session_id)
    assert created == 1
    # idempotent: no duplicate pending tasks
    assert rebuild_review_plan(session_id) == 0

    tasks = list_reviews(session_id)
    assert len(tasks) == 1
    result = complete_review(session_id, tasks[0].id, correct=False)
    assert result["status"] == "completed"
    assert result["follow_up_task_id"] is not None


def test_question_bank_idempotent(engine):
    from app.services.question_bank import ensure_question_bank

    session_id = "qb-session"
    course_id = _seed_document(session_id)
    first = ensure_question_bank(session_id, course_id)
    second = ensure_question_bank(session_id, course_id)
    assert first > 0
    assert second == 0
