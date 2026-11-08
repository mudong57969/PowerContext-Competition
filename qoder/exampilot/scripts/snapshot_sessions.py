import os

"""Snapshot the 5 test sessions' state before auth migration (read-only)."""

import pymysql

SOCK = os.environ.get("EXAMPILOT_SEEKDB_SOCKET") or os.path.expanduser(
    "~/exampilot-data/seekdb-exampilot/run/sql.sock"
)


def main() -> None:
    conn = pymysql.connect(
        unix_socket=SOCK, user="root", database="test", charset="utf8mb4"
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, scope_id, created_at FROM demo_sessions ORDER BY created_at"
            )
            sessions = cur.fetchall()
            for s in sessions:
                sid, name, scope, created = s
                print(f"session {sid} name={name!r} scope={scope} created={created}")
                cur.execute(
                    "SELECT COUNT(*) FROM documents WHERE session_id=%s", (sid,)
                )
                print(f"  documents: {cur.fetchone()[0]}")
                cur.execute("SELECT COUNT(*) FROM courses WHERE session_id=%s", (sid,))
                print(f"  courses: {cur.fetchone()[0]}")
                cur.execute(
                    "SELECT COUNT(*) FROM questions WHERE session_id=%s", (sid,)
                )
                print(f"  questions: {cur.fetchone()[0]}")
                cur.execute(
                    "SELECT COUNT(*) FROM practice_sessions WHERE session_id=%s", (sid,)
                )
                print(f"  practice_sessions: {cur.fetchone()[0]}")
                cur.execute(
                    "SELECT COUNT(*) FROM review_tasks WHERE session_id=%s", (sid,)
                )
                print(f"  review_tasks: {cur.fetchone()[0]}")
                cur.execute(
                    "SELECT COUNT(*) FROM memory_events WHERE session_id=%s", (sid,)
                )
                print(f"  memory_events: {cur.fetchone()[0]}")
                cur.execute(
                    "SELECT COUNT(*) FROM knowledge_mastery WHERE session_id=%s", (sid,)
                )
                print(f"  knowledge_mastery: {cur.fetchone()[0]}")
                cur.execute(
                    "SELECT COUNT(*) FROM attempts a JOIN practice_sessions p "
                    "ON a.practice_session_id=p.id WHERE p.session_id=%s AND a.is_correct=0",
                    (sid,),
                )
                print(f"  wrong attempts: {cur.fetchone()[0]}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
