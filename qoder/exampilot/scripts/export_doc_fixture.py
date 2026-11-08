"""Export a document's real extracted pages from seekdb as a JSON test fixture.

Read-only probe: exports page_number + original_text per chunk, so offline
regression tests can run the classifier on the exact text the real pipeline
extracted. Usage (WSL):

    python scripts/export_doc_fixture.py <doc_id> backend/tests/fixtures/<name>.json
"""

import argparse
import json
import os

import pymysql

SOCK = os.environ.get("EXAMPILOT_SEEKDB_SOCKET") or os.path.expanduser(
    "~/exampilot-data/seekdb-exampilot/run/sql.sock"
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("doc_id", type=int)
    ap.add_argument("out", help="output JSON path (Windows path is fine)")
    args = ap.parse_args()

    conn = pymysql.connect(
        unix_socket=SOCK, user="root", database="test", charset="utf8mb4"
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT page_number, original_text FROM document_chunks "
                "WHERE document_id=%s ORDER BY chunk_index, page_number",
                (args.doc_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    pages = [{"page_number": r[0], "text": r[1]} for r in rows if r[1] and r[1].strip()]
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(pages, f, ensure_ascii=False, indent=1)
    print(
        f"exported {len(pages)} pages ({sum(len(p['text']) for p in pages)} chars) to {args.out}"
    )


if __name__ == "__main__":
    main()
