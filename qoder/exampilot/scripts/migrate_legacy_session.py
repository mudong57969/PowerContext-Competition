import os

"""Controlled local migration: issue an identity token for a legacy session.

Legacy demo_sessions predate the bearer-token auth system and have no
``identities`` row, so their data is inaccessible through the API by design
(default-deny). This script is the only way to (re)bind such a session, and
it must be run deliberately on the local machine by the operator.

The token is generated with 256 bits of randomness, printed exactly once,
and only its SHA-256 digest is stored.

Usage (WSL, from backend/):
    python scripts/migrate_legacy_session.py <session_id> [--name "new name"]
"""

import argparse
import secrets

import pymysql

SOCK = os.environ.get("EXAMPILOT_SEEKDB_SOCKET") or os.path.expanduser(
    "~/exampilot-data/seekdb-exampilot/run/sql.sock"
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("session_id")
    ap.add_argument("--name", default=None, help="optionally rename the session")
    args = ap.parse_args()

    conn = pymysql.connect(
        unix_socket=SOCK, user="root", database="test", charset="utf8mb4"
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name FROM demo_sessions WHERE id=%s", (args.session_id,)
            )
            row = cur.fetchone()
            if row is None:
                print(f"session not found: {args.session_id}")
                return
            cur.execute(
                "SELECT COUNT(*) FROM identities WHERE session_id=%s",
                (args.session_id,),
            )
            if cur.fetchone()[0] > 0:
                print(
                    f"session {args.session_id} already has an identity; "
                    "refusing to rotate (data is not lost, token stays as issued)"
                )
                return
            token = secrets.token_urlsafe(32)
            digest = __import__("hashlib").sha256(token.encode("utf-8")).hexdigest()
            cur.execute(
                "INSERT INTO identities (session_id, token_digest) VALUES (%s, %s)",
                (args.session_id, digest),
            )
            if args.name:
                cur.execute(
                    "UPDATE demo_sessions SET name=%s WHERE id=%s",
                    (args.name, args.session_id),
                )
            conn.commit()
    finally:
        conn.close()

    print(f"identity created for session {args.session_id} (name={row[1]!r})")
    print("copy this token into the frontend (it is shown only once):")
    print(token)


if __name__ == "__main__":
    main()
