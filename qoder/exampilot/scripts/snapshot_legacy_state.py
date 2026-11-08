import os

"""Snapshot legacy-session data counts before/after identity migration."""

import pymysql

SOCK = os.environ.get("EXAMPILOT_SEEKDB_SOCKET") or os.path.expanduser(
    "~/exampilot-data/seekdb-exampilot/run/sql.sock"
)

LEGACY = [
    "27a291634c6f4297",
    "fd03b69768d343b2",
    "9e7fc0f065134af5",
    "0672a230825e4502",
    "d181a2a90f614248",
]

QUERIES = [
    ("demo_sessions", "SELECT COUNT(*) FROM demo_sessions WHERE id=%s"),
    ("courses", "SELECT COUNT(*) FROM courses WHERE session_id=%s"),
    (
        "chapters",
        (
            "SELECT COUNT(*) FROM chapters ch JOIN courses co ON ch.course_id=co.id "
            "WHERE co.session_id=%s"
        ),
    ),
    ("documents", "SELECT COUNT(*) FROM documents WHERE session_id=%s"),
    (
        "document_chunks",
        (
            "SELECT COUNT(*) FROM document_chunks dc JOIN documents d ON dc.document_id=d.id "
            "WHERE d.session_id=%s"
        ),
    ),
    (
        "document_knowledge_links",
        (
            "SELECT COUNT(*) FROM document_knowledge_links dk JOIN documents d "
            "ON dk.document_id=d.id WHERE d.session_id=%s"
        ),
    ),
    (
        "knowledge_points",
        (
            "SELECT COUNT(*) FROM knowledge_points kp JOIN courses co ON kp.course_id=co.id "
            "WHERE co.session_id=%s"
        ),
    ),
    ("questions", "SELECT COUNT(*) FROM questions WHERE session_id=%s"),
    (
        "question_knowledge_links",
        (
            "SELECT COUNT(*) FROM question_knowledge_links qk JOIN questions q "
            "ON qk.question_id=q.id WHERE q.session_id=%s"
        ),
    ),
    ("practice_sessions", "SELECT COUNT(*) FROM practice_sessions WHERE session_id=%s"),
    (
        "attempts",
        (
            "SELECT COUNT(*) FROM attempts a JOIN practice_sessions ps "
            "ON a.practice_session_id=ps.id WHERE ps.session_id=%s"
        ),
    ),
    (
        "knowledge_mastery",
        (
            "SELECT COUNT(*) FROM knowledge_mastery km JOIN knowledge_points kp "
            "ON km.knowledge_point_id=kp.id JOIN courses co ON kp.course_id=co.id "
            "WHERE co.session_id=%s"
        ),
    ),
    ("review_tasks", "SELECT COUNT(*) FROM review_tasks WHERE session_id=%s"),
    (
        "classification_feedback",
        (
            "SELECT COUNT(*) FROM classification_feedback cf JOIN documents d "
            "ON cf.document_id=d.id WHERE d.session_id=%s"
        ),
    ),
    ("memory_events", "SELECT COUNT(*) FROM memory_events WHERE session_id=%s"),
    ("user_preferences", "SELECT COUNT(*) FROM user_preferences WHERE session_id=%s"),
    ("identities", "SELECT COUNT(*) FROM identities WHERE session_id=%s"),
]


def main() -> None:
    conn = pymysql.connect(
        unix_socket=SOCK, user="root", database="test", charset="utf8mb4"
    )
    try:
        with conn.cursor() as cur:
            for sid in LEGACY:
                print(f"session {sid}")
                for name, sql in QUERIES:
                    cur.execute(sql, (sid,))
                    print(f"  {name}: {cur.fetchone()[0]}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
