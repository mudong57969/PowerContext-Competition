import os

"""UAT2: verify every cited slide in kp_evidence actually contains a KP keyword."""

import json
from collections import defaultdict

import pymysql

from app.services.classification import DOMAIN_KP_KEYWORDS, _count_term, _norm

SOCK = os.environ.get("EXAMPILOT_SEEKDB_SOCKET") or os.path.expanduser(
    "~/exampilot-data/seekdb-exampilot/run/sql.sock"
)


def main() -> None:
    conn = pymysql.connect(
        unix_socket=SOCK, user="root", database="test", charset="utf8mb4"
    )
    with conn.cursor() as cur:
        cur.execute("SELECT classify_evidence FROM documents WHERE id=1000002")
        ev = json.loads(cur.fetchone()[0])
        cur.execute(
            "SELECT page_number, original_text FROM document_chunks "
            "WHERE document_id=1000002 ORDER BY chunk_index"
        )
        rows = cur.fetchall()
    conn.close()

    pages: dict[int, str] = defaultdict(str)
    for pn, txt in rows:
        pages[int(pn)] += (txt or "") + "\n"

    kp_kws = dict(DOMAIN_KP_KEYWORDS.get("数字集成电路", []))
    print(
        "KP evidence verification for document 1000002 (chunks concatenated per page)"
    )
    print("=" * 70)
    all_ok = True
    for name, slides in ev.get("kp_evidence", {}).items():
        bad = [
            s
            for s in slides
            if not any(
                _count_term(_norm(pages[int(s)]), kw) > 0 for kw in kp_kws.get(name, [])
            )
        ]
        if bad:
            all_ok = False
        print(
            f"[{'OK' if not bad else 'FAIL'}] {name}: cited {len(slides)} slides, without-keyword: {bad or '-'}"
        )
    print("=" * 70)
    print("OVERALL:", "PASS" if all_ok else "FAIL")


if __name__ == "__main__":
    main()
