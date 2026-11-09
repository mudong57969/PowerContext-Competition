"""Write the current task state into PowerContext as an explicit Memory entry.

The task state is a single-value slot with history:

* writing a state that is not stored yet creates a new Atomic Memory;
* writing a state whose text is already the current one reuses it;
* every other active task state is **forgotten** (its content and revision
  stay readable as history), so exactly one active state describes "now" and
  the previous state remains distinguishable from the current one.

Usage:

    python3 minimax/remember_state.py "状态正文" "写入原因（可选）"
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pc_client  # noqa: E402
from ingest import resolve_scope_id  # noqa: E402

DEFAULT_STATE = "目标测试失败，待修复"
STATE_KIND = "task-state"


def _artifact(entry: dict) -> dict:
    return entry.get("artifact") or {}


def main(argv: list[str]) -> int:
    text = argv[1] if len(argv) > 1 else DEFAULT_STATE
    reason = argv[2] if len(argv) > 2 else None
    scope_id = resolve_scope_id()

    print(f"scope_id: {scope_id}")
    print(f"server:   {pc_client.base_url()}")
    print(f"wrote:    {text}")
    if reason:
        print(f"reason:   {reason}")

    active = pc_client.list_atomic_memory(scope_id, kind=STATE_KIND, states=["active"])

    current = next((entry for entry in active if entry.get("text") == text), None)
    if current is not None:
        artifact = _artifact(current)
        print(
            f"reused existing state: {artifact.get('artifact_id')} "
            f"rev={artifact.get('revision')} state={current.get('state')}"
        )
    else:
        response = pc_client.remember(scope_id, kind=STATE_KIND, text=text, reason=reason)
        print(f"response: {response}")
        records = response.get("records") or []
        if records:
            artifact = _artifact(records[0])
            print(
                f"created state: {artifact.get('artifact_id')} "
                f"rev={artifact.get('revision')} state={records[0].get('state')}"
            )

    # supersede every other active task state
    for entry in active:
        if entry.get("text") == text:
            continue
        artifact = _artifact(entry)
        artifact_id = artifact.get("artifact_id")
        pc_client.forget_atomic_memory(
            scope_id,
            artifact_id,
            artifact.get("revision"),
            entry.get("state_version", 0),
        )
        print(f"superseded state: {artifact_id} rev={artifact.get('revision')} — {entry.get('text')}")

    print("current states:")
    for entry in pc_client.list_atomic_memory(scope_id, kind=STATE_KIND):
        artifact = _artifact(entry)
        marker = "*" if entry.get("state") == "active" else " "
        print(
            f" {marker} {artifact.get('artifact_id')} rev={artifact.get('revision')} "
            f"state={entry.get('state')}: {entry.get('text')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
