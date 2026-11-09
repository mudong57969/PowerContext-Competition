"""Import the MiniMax sample materials into the PowerContext Server.

This is the initialization step of the sample: it creates (or reuses) one
Scope, imports the business specification, the implementation and the test
module as durable Content Sources, and writes the runtime state file
``minimax/state/scope.json``.

Source ids encode what the record is, so a later query can tell versions
apart:

* the specification keeps one id per version (``minimax-spec-v2``), so
  re-importing a new version adds a record instead of overwriting the old one;
* the implementation and the test module carry a content digest
  (``minimax-code-<sha8>``), so editing a file produces a new record while an
  unchanged file stays idempotent.

Every Source carries the real absolute path of the file it was built from.

Usage:

    python3 minimax/ingest.py
    python3 minimax/ingest.py --spec minimax/samples/SPEC.v1.md
    python3 minimax/ingest.py --scope-key my-reset-1
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pc_client  # noqa: E402

HERE = Path(__file__).resolve().parent
STATE_DIR = HERE / "state"
STATE_FILE = STATE_DIR / "scope.json"

SCOPE_TITLE = "MiniMax 任务状态样例"
SCOPE_SUMMARY = "minimax 赛道的最小任务状态样例：业务规格、实现与测试。"
SCOPE_IDEMPOTENCY_KEY = "minimax-task-status-sample"

SPEC_PATH = HERE / "SPEC.md"
CODE_PATH = HERE / "task_status.py"
TEST_PATH = HERE / "test_task_status.py"

_VERSION_PATTERN = re.compile(r"^版本:\s*(\S+)\s*$", re.MULTILINE)


def resolve_scope_id() -> str:
    """Return the Scope id from the environment or the saved state file."""
    scope_id = os.environ.get("POWERCONTEXT_SCOPE_ID")
    if scope_id:
        return scope_id
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())["scope_id"]
    raise SystemExit(
        f"no Scope id available: run ingest.py first or set POWERCONTEXT_SCOPE_ID (looked at {STATE_FILE})"
    )


def save_scope_id(scope_id: str) -> None:
    """Create the runtime state file at initialization time."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(
            {
                "scope_id": scope_id,
                "server_url": pc_client.base_url(),
                "created_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def spec_version(body: str) -> str:
    """Read the ``版本:`` marker out of the specification."""
    match = _VERSION_PATTERN.search(body)
    return match.group(1) if match else "unversioned"


def source_id_for(role: str, path: Path, body: str) -> str:
    """Build a stable Source id for one file."""
    if role == "spec":
        return f"minimax-spec-{spec_version(body)}"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:8]
    return f"minimax-{role}-{digest}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import the sample materials into PowerContext.")
    parser.add_argument(
        "--spec",
        default=str(SPEC_PATH),
        help="specification file to import (default: minimax/SPEC.md)",
    )
    parser.add_argument(
        "--scope-key",
        default=os.environ.get("MINIMAX_SCOPE_KEY", SCOPE_IDEMPOTENCY_KEY),
        help="scope idempotency key; use a new value to start a fresh sample scope",
    )
    args = parser.parse_args(argv)

    spec_path = Path(args.spec).resolve()
    scope_id = pc_client.create_scope(SCOPE_TITLE, SCOPE_SUMMARY, args.scope_key)
    print(f"scope_id: {scope_id}")
    print(f"server:   {pc_client.base_url()}")
    print(f"spec:     {spec_path}")
    print(f"scope_key:{args.scope_key}")
    print()

    for role, path in (("spec", spec_path), ("code", CODE_PATH), ("test", TEST_PATH)):
        absolute = path.resolve()
        body = absolute.read_text()
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        source_id = source_id_for(role, absolute, body)
        content = f"# source_path: {absolute}\n# source_role: {role}\n\n{body}"
        try:
            response = pc_client.capture_content_source(
                scope_id,
                source_id,
                content,
                metadata={
                    "path": str(absolute),
                    "role": role,
                    "sha256": digest,
                    "version": spec_version(body) if role == "spec" else digest[:8],
                },
            )
            print(f"[{role}] source_id={source_id} -> {response.get('status')} position={response.get('position')}")
        except pc_client.PowerContextError as error:
            if "HTTP 409" in str(error):
                print(f"[{role}] source_id={source_id} -> already present (skipped)")
            else:
                print(f"[{role}] source_id={source_id} -> ERROR {error}")
                continue
        print(f"       path={absolute}")

    save_scope_id(scope_id)
    print()
    print(f"saved scope id -> {STATE_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
