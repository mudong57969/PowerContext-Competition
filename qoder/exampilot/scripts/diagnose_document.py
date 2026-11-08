"""Read-only diagnosis of one uploaded document in the live seekdb engine.

Connects as an external client over the engine's unix socket (read-only
SELECTs only). Usage (inside WSL, backend running):

    python scripts/diagnose_document.py <filename_substring>
"""

from __future__ import annotations

import json
import os
import sys

import pymysql

SOCKET = os.environ.get("EXAMPILOT_SEEKDB_SOCKET") or os.path.expanduser(
    "~/exampilot-data/seekdb-exampilot/run/sql.sock"
)


def main() -> None:
    needle = sys.argv[1] if len(sys.argv) > 1 else "MOS-dynamic"
    conn = pymysql.connect(
        unix_socket=SOCKET, user="root", database="test", charset="utf8mb4"
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, session_id, course_id, chapter_id, filename, file_type, "
                "file_hash, file_size, page_count, parse_status, classify_status, "
                "classify_confidence, ocr_required, created_at, updated_at "
                "FROM documents WHERE filename LIKE %s ORDER BY id DESC",
                (f"%{needle}%",),
            )
            rows = cur.fetchall()
            if not rows:
                print("NO MATCHING DOCUMENT")
                return
            for row in rows:
                doc_id, session_id = int(row[0]), str(row[1])
                print("=" * 70)
                print(f"document_id        : {doc_id}")
                print(f"session_id         : {session_id}")
                print(f"course_id          : {row[2]}")
                print(f"chapter_id         : {row[3]}")
                print(f"filename           : {row[4]}")
                print(f"file_type          : {row[5]}")
                print(f"file_size(bytes)   : {row[7]}")
                print(f"page_count         : {row[8]}")
                print(f"parse_status       : {row[9]}")
                print(f"classify_status    : {row[10]}")
                print(f"classify_confidence: {row[11]}")
                print(f"ocr_required       : {row[12]}")
                print(f"created_at         : {row[13]}")
                print(f"updated_at         : {row[14]}")
                cur.execute(
                    "SELECT classify_evidence FROM documents WHERE id=%s", (doc_id,)
                )
                ev = cur.fetchone()[0]
                print("classify_evidence  :")
                if ev:
                    try:
                        print(json.dumps(json.loads(ev), ensure_ascii=False, indent=2))
                    except Exception:  # noqa: BLE001 - print raw evidence when unparseable
                        print(ev)
                else:
                    print("  (none)")
                # chunk stats
                cur.execute(
                    "SELECT COUNT(*), "
                    "COALESCE(SUM(CHAR_LENGTH(original_text)),0), "
                    "COALESCE(SUM(CHAR_LENGTH(normalized_text)),0), "
                    "COUNT(embedding), COUNT(DISTINCT page_number) "
                    "FROM document_chunks WHERE document_id=%s",
                    (doc_id,),
                )
                c = cur.fetchone()
                print(f"chunks             : {int(c[0])}")
                print(f"original_chars     : {int(c[1])}")
                print(f"normalized_chars   : {int(c[2])}")
                print(f"chunks_with_embed  : {int(c[3])}")
                print(f"distinct_pages     : {int(c[4])}")
                # sample first 6 chunks (page number + first 160 chars)
                cur.execute(
                    "SELECT page_number, original_text FROM document_chunks "
                    "WHERE document_id=%s ORDER BY chunk_index LIMIT 6",
                    (doc_id,),
                )
                print("sample_chunks      :")
                for pn, txt in cur.fetchall():
                    t = (txt or "").replace("\n", "\\n")
                    print(f"  [page {pn}] {t[:160]}")
                # slides with empty text? pages are indexed only if non-empty;
                # empty slide count = page_count - distinct_pages (approx)
                print(f"approx_empty_slides: {max(0, int(row[8]) - int(c[4]))}")
                # courses existing for this session
                cur.execute(
                    "SELECT id, name, confidence, status FROM courses "
                    "WHERE session_id=%s ORDER BY id",
                    (session_id,),
                )
                print("existing_courses   :")
                for cr in cur.fetchall():
                    print(f"  id={cr[0]} name={cr[1]!r} conf={cr[2]} status={cr[3]}")
                cur.execute(
                    "SELECT ch.name, COUNT(*) FROM document_chunks dc "
                    "JOIN chapters ch ON dc.chapter_id=ch.id "
                    "WHERE dc.document_id=%s GROUP BY ch.name",
                    (doc_id,),
                )
                print("chunk_chapters     :", cur.fetchall())
    finally:
        conn.close()


if __name__ == "__main__":
    main()
