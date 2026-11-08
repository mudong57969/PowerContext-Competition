"""Dump per-page keyword presence for the diagnosed document (read-only)."""

from __future__ import annotations

import os
import sys

import pymysql

SOCKET = os.environ.get("EXAMPILOT_SEEKDB_SOCKET") or os.path.expanduser(
    "~/exampilot-data/seekdb-exampilot/run/sql.sock"
)
TERMS = [
    "velocity saturation",
    "short-channel",
    "short channel",
    "threshold",
    "body effect",
    "channel length modulation",
    "leakage",
    "dynamic",
    "inverter",
    "vtc",
    "power",
    "delay",
    "interconnect",
    "scaling",
    "latchup",
    "process variation",
    "i-v",
    "iv characteristics",
]


def main() -> None:
    doc_id = sys.argv[1] if len(sys.argv) > 1 else "1000002"
    conn = pymysql.connect(
        unix_socket=SOCKET, user="root", database="test", charset="utf8mb4"
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT page_number, original_text FROM document_chunks "
                "WHERE document_id=%s ORDER BY chunk_index",
                (doc_id,),
            )
            rows = cur.fetchall()
            print(f"total chunks: {len(rows)}")
            for pn, txt in rows:
                low = (txt or "").lower()
                hits = [t for t in TERMS if t in low]
                if hits:
                    first = (txt or "").strip().split("\n")[0][:60]
                    print(f"[page {pn}] hits={hits} | first_line={first!r}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
