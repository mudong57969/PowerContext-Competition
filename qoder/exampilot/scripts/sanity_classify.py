"""Sanity-check the new classifier against the real extracted text of the
diagnosed PPTX (read-only: chunks are read over the engine socket; the
DB-touching classifier functions are stubbed)."""

from __future__ import annotations

import json
import os
import sys

import pymysql

sys.path.insert(0, "/mnt/d/oceanbase_comp/qoder-project/qoder/exampilot/backend")

from app.services.classification import classify_document
from app.services.parsing import ParsedPage, ParseResult

SOCKET = os.environ.get("EXAMPILOT_SEEKDB_SOCKET") or os.path.expanduser(
    "~/exampilot-data/seekdb-exampilot/run/sql.sock"
)


def main() -> None:
    doc_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1000002
    conn = pymysql.connect(
        unix_socket=SOCKET, user="root", database="test", charset="utf8mb4"
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT filename FROM documents WHERE id=%s", (doc_id,))
            filename = str(cur.fetchone()[0])
            cur.execute(
                "SELECT page_number, original_text FROM document_chunks "
                "WHERE document_id=%s ORDER BY chunk_index",
                (doc_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    pages_by_no: dict[int, list[str]] = {}
    order: list[int] = []
    for page_no, original in rows:
        pn = int(page_no)
        if pn not in pages_by_no:
            pages_by_no[pn] = []
            order.append(pn)
        pages_by_no[pn].append(original or "")
    pages = [
        ParsedPage(page_number=pn, text="\n".join(pages_by_no[pn])) for pn in order
    ]
    parse_result = ParseResult(pages=pages)

    import app.services.classification as mod

    mod._existing_courses = lambda sid: []
    mod._retrieval_signal = lambda sid, text: (None, 0.0)
    mod._existing_chapters = lambda sid, cid: []

    decision = classify_document("sanity-session", filename, parse_result, 0.65, 0.45)
    print(
        json.dumps(
            {
                "filename": filename,
                "total_chars": parse_result.total_chars,
                "pages": len(pages),
                "course": decision.course,
                "chapter": decision.chapter,
                "confidence": decision.confidence,
                "status": decision.status,
                "reason": decision.reason,
                "knowledge_points": decision.knowledge_points,
                "kp_evidence": decision.kp_evidence,
                "course_candidates": decision.course_candidates,
                "chapter_candidates": decision.chapter_candidates,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
