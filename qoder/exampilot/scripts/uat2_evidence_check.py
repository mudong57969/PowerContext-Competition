import os

"""UAT2-4 probe: dump classify_evidence of the UAT2 docs to show what the
list endpoint actually renders (candidates come from stored evidence, not
from the upload response). Read-only."""

import json

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
                "SELECT id, filename, classify_status, classify_confidence, classify_evidence "
                "FROM documents WHERE id BETWEEN 2000001 AND 2000004 ORDER BY id"
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    for r in rows:
        doc_id, fname, status, conf, raw = r
        try:
            ev = json.loads(raw) if raw else {}
        except Exception:  # noqa: BLE001 - unparseable evidence is reported as-is
            ev = {"__unparseable__": raw[:200]}
        print(f"doc {doc_id} {fname}: status={status} conf={conf}")
        print(f"  evidence keys: {sorted(ev.keys())}")
        print(
            f"  course={ev.get('course')!r} course_confidence={ev.get('course_confidence')!r}"
        )
        print(f"  course_candidates stored: {ev.get('course_candidates')!r}")
        print(
            f"  chapter={ev.get('chapter')!r} chapter_confidence={ev.get('chapter_confidence')!r}"
        )
        print(f"  reason={ev.get('reason')!r}")


if __name__ == "__main__":
    main()
