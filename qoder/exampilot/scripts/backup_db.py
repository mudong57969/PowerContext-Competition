"""Logical backup of the ExamPilot seekdb business database (pre-auth-fix).

Read-only: dumps SHOW CREATE TABLE + all rows as INSERT statements so the
pre-fix state can be restored if anything goes wrong during UAT3 fixes.

Usage (WSL):
    python scripts/backup_db.py evidence/backup_20261107
"""

import argparse
import os
from datetime import UTC, datetime

import pymysql

SOCK = os.environ.get("EXAMPILOT_SEEKDB_SOCKET") or os.path.expanduser(
    "~/exampilot-data/seekdb-exampilot/run/sql.sock"
)


def _lit(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (bytes, bytearray)):
        return "X'" + v.hex() + "'"
    s = str(v)
    return "'" + s.replace("\\", "\\\\").replace("'", "''") + "'"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    conn = pymysql.connect(
        unix_socket=SOCK, user="root", database="test", charset="utf8mb4"
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW TABLES")
            tables = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()

    out = [
        f"-- ExamPilot seekdb logical backup {datetime.now(UTC).isoformat()}",
        f"-- tables: {len(tables)}",
        "SET NAMES utf8mb4;",
    ]
    counts = []
    for t in tables:
        conn = pymysql.connect(
            unix_socket=SOCK, user="root", database="test", charset="utf8mb4"
        )
        try:
            with conn.cursor() as cur:
                cur.execute(f"SHOW CREATE TABLE `{t}`")
                ddl = cur.fetchone()[1]
                cur.execute(f"SELECT COUNT(*) FROM `{t}`")
                n = cur.fetchone()[0]
            counts.append((t, n))
            out.append(f"\n-- ===== TABLE {t} ({n} rows) =====")
            out.append(ddl + ";")
            if n:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT * FROM `{t}`")
                    cols = [d[0] for d in cur.description]
                    rows = cur.fetchall()
                for row in rows:
                    out.append(
                        f"INSERT INTO `{t}` (`{'`,`'.join(cols)}`) VALUES "
                        f"({','.join(_lit(v) for v in row)});"
                    )
        finally:
            conn.close()

    with open(
        os.path.join(args.outdir, "seekdb_backup.sql"), "w", encoding="utf-8"
    ) as f:
        f.write("\n".join(out) + "\n")

    print("table row counts:")
    for t, n in counts:
        print(f"  {t}: {n}")
    print(f"backup written to {os.path.join(args.outdir, 'seekdb_backup.sql')}")
    print(f"total tables: {len(tables)}")


if __name__ == "__main__":
    main()
