"""Database schema (seekdb DDL).

All ExamPilot structured data lives in the embedded seekdb engine.
Tables use logical constraints (indexes) instead of foreign keys for
compatibility with the embedded engine.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.core.seekdb import get_engine

EMBEDDING_DIM = get_settings().embedding_dimension

SCHEMA_STATEMENTS: list[str] = [
    # --- users / demo sessions -------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS demo_sessions (
        id VARCHAR(64) PRIMARY KEY,
        name VARCHAR(128) NOT NULL DEFAULT '',
        scope_id VARCHAR(128) NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # --- courses / chapters / knowledge points ---------------------------
    """
    CREATE TABLE IF NOT EXISTS courses (
        id INT AUTO_INCREMENT PRIMARY KEY,
        session_id VARCHAR(64) NOT NULL,
        name VARCHAR(256) NOT NULL,
        confidence FLOAT NOT NULL DEFAULT 0,
        status VARCHAR(32) NOT NULL DEFAULT 'auto',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        KEY idx_courses_session (session_id),
        KEY idx_courses_name (name(64))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chapters (
        id INT AUTO_INCREMENT PRIMARY KEY,
        course_id INT NOT NULL,
        name VARCHAR(256) NOT NULL,
        order_index INT NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        KEY idx_chapters_course (course_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_points (
        id INT AUTO_INCREMENT PRIMARY KEY,
        course_id INT NOT NULL,
        chapter_id INT NULL,
        name VARCHAR(256) NOT NULL,
        description TEXT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        KEY idx_kp_course (course_id),
        KEY idx_kp_chapter (chapter_id)
    )
    """,
    # --- documents --------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS documents (
        id INT AUTO_INCREMENT PRIMARY KEY,
        session_id VARCHAR(64) NOT NULL,
        course_id INT NULL,
        chapter_id INT NULL,
        filename VARCHAR(512) NOT NULL,
        file_type VARCHAR(16) NOT NULL,
        file_hash VARCHAR(64) NOT NULL,
        file_size INT NOT NULL,
        page_count INT NOT NULL DEFAULT 0,
        parse_status VARCHAR(32) NOT NULL DEFAULT 'pending',
        classify_status VARCHAR(32) NOT NULL DEFAULT 'pending',
        classify_confidence FLOAT NOT NULL DEFAULT 0,
        classify_evidence TEXT NULL,
        ocr_required TINYINT NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        KEY idx_docs_session (session_id),
        KEY idx_docs_course (course_id),
        KEY idx_docs_hash (file_hash),
        UNIQUE KEY uq_docs_session_hash (session_id, file_hash)
    )
    """,
    # --- document chunks (fulltext + vector indexes) ---------------------
    f"""
    CREATE TABLE IF NOT EXISTS document_chunks (
        id INT AUTO_INCREMENT PRIMARY KEY,
        document_id INT NOT NULL,
        course_id INT NULL,
        chapter_id INT NULL,
        chunk_index INT NOT NULL,
        page_number INT NOT NULL DEFAULT 0,
        original_text TEXT NOT NULL,
        normalized_text TEXT NOT NULL,
        fts_text TEXT NOT NULL,
        embedding VECTOR({EMBEDDING_DIM}) NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        KEY idx_chunks_doc (document_id),
        KEY idx_chunks_course (course_id),
        FULLTEXT KEY ft_chunks_text (fts_text)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS document_knowledge_links (
        document_id INT NOT NULL,
        knowledge_point_id INT NOT NULL,
        slide_numbers TEXT NULL,
        PRIMARY KEY (document_id, knowledge_point_id)
    )
    """,
    # --- questions --------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS questions (
        id INT AUTO_INCREMENT PRIMARY KEY,
        session_id VARCHAR(64) NULL,
        course_id INT NULL,
        chapter_id INT NULL,
        question_type VARCHAR(16) NOT NULL,
        stem TEXT NOT NULL,
        options TEXT NULL,
        answer TEXT NOT NULL,
        explanation TEXT NOT NULL,
        source_document_id INT NULL,
        source_quote TEXT NULL,
        difficulty INT NOT NULL DEFAULT 2,
        is_generated TINYINT NOT NULL DEFAULT 0,
        review_status VARCHAR(32) NOT NULL DEFAULT 'approved',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        KEY idx_questions_session (session_id),
        KEY idx_questions_course (course_id),
        KEY idx_questions_type (question_type)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS question_knowledge_links (
        question_id INT NOT NULL,
        knowledge_point_id INT NOT NULL,
        PRIMARY KEY (question_id, knowledge_point_id)
    )
    """,
    # --- practice / attempts / mastery -----------------------------------
    """
    CREATE TABLE IF NOT EXISTS practice_sessions (
        id INT AUTO_INCREMENT PRIMARY KEY,
        session_id VARCHAR(64) NOT NULL,
        course_id INT NULL,
        mode VARCHAR(32) NOT NULL DEFAULT 'practice',
        total_questions INT NOT NULL DEFAULT 0,
        correct_count INT NOT NULL DEFAULT 0,
        score FLOAT NULL,
        started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        finished_at DATETIME NULL,
        KEY idx_ps_session (session_id),
        KEY idx_ps_course (course_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS attempts (
        id INT AUTO_INCREMENT PRIMARY KEY,
        practice_session_id INT NOT NULL,
        question_id INT NOT NULL,
        user_answer TEXT NULL,
        is_correct TINYINT NULL,
        score FLOAT NULL,
        grading_evidence TEXT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        KEY idx_attempts_session (practice_session_id),
        KEY idx_attempts_question (question_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_mastery (
        session_id VARCHAR(64) NOT NULL,
        knowledge_point_id INT NOT NULL,
        practice_count INT NOT NULL DEFAULT 0,
        correct_count INT NOT NULL DEFAULT 0,
        streak INT NOT NULL DEFAULT 0,
        last_practiced_at DATETIME NULL,
        mastery_score FLOAT NOT NULL DEFAULT 0,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (session_id, knowledge_point_id)
    )
    """,
    # --- review tasks -----------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS review_tasks (
        id INT AUTO_INCREMENT PRIMARY KEY,
        session_id VARCHAR(64) NOT NULL,
        course_id INT NULL,
        knowledge_point_id INT NULL,
        due_date DATE NULL,
        reason TEXT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'pending',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        completed_at DATETIME NULL,
        KEY idx_review_session (session_id),
        KEY idx_review_status (status)
    )
    """,
    # --- classification feedback / audit ---------------------------------
    """
    CREATE TABLE IF NOT EXISTS classification_feedback (
        id INT AUTO_INCREMENT PRIMARY KEY,
        document_id INT NOT NULL,
        original_json TEXT NULL,
        corrected_json TEXT NULL,
        user_confirmed TINYINT NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        KEY idx_cf_document (document_id)
    )
    """,
    # --- memory write audit (PowerContext evidence) ----------------------
    """
    CREATE TABLE IF NOT EXISTS memory_events (
        id INT AUTO_INCREMENT PRIMARY KEY,
        session_id VARCHAR(64) NOT NULL,
        scope_id VARCHAR(128) NOT NULL,
        kind VARCHAR(128) NOT NULL,
        summary TEXT NOT NULL,
        memory_reference TEXT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'ok',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        KEY idx_me_session (session_id)
    )
    """,
    # --- user preferences ------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS user_preferences (
        session_id VARCHAR(64) PRIMARY KEY,
        exam_date DATE NULL,
        goal TEXT NULL,
        preferred_language VARCHAR(16) NOT NULL DEFAULT 'zh',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # --- anonymous learning identities (bearer-token auth) ---------------
    # Only the SHA-256 digest of the bearer token is stored; the token
    # itself is returned once at identity creation and never persisted.
    """
    CREATE TABLE IF NOT EXISTS identities (
        session_id VARCHAR(64) PRIMARY KEY,
        token_digest VARCHAR(64) NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_used_at DATETIME NULL,
        KEY idx_identities_digest (token_digest)
    )
    """,
]


def vector_index_ddl() -> str:
    return (
        "CREATE VECTOR INDEX IF NOT EXISTS vec_chunks_embedding "
        "ON document_chunks (embedding) WITH (distance=L2, type=HNSW)"
    )


def _ensure_column(cur, table: str, column: str, ddl: str) -> None:
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema=DATABASE() AND table_name=%s AND column_name=%s",
        (table, column),
    )
    if int(cur.fetchone()[0]) == 0:
        cur.execute(ddl)


def create_all_tables() -> None:
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        for stmt in SCHEMA_STATEMENTS:
            cur.execute(stmt)
        # Non-destructive migration: KP links carry slide-number evidence
        _ensure_column(
            cur,
            "document_knowledge_links",
            "slide_numbers",
            "ALTER TABLE document_knowledge_links ADD COLUMN slide_numbers TEXT NULL",
        )
        try:
            cur.execute(vector_index_ddl())
        except Exception as exc:  # pragma: no cover - engine-specific  # noqa: BLE001
            from app.core.logging import get_logger

            get_logger(__name__).warning("vector index creation skipped: %s", exc)


def table_names() -> list[str]:
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute("SHOW TABLES")
        return [row[0] for row in cur.fetchall()]
