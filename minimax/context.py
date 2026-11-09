"""``context`` — assemble the working context for the MiniMax sample.

Every value printed here comes from a live query against the PowerContext
Server (storage: seekdb). Nothing is hard-coded:

1. ``POST /v1/scopes/{scope_id}/sources``      -> the imported material:
   the business specification, the implementation and the test module. When
   the specification was imported more than once, the **current version** is
   selected (highest version number, then latest position) and the older
   versions are reported as archived;
2. ``POST /v1/memory/entries/list``            -> the task states written
   through PowerContext, with their artifact revision and active state;
3. ``POST /v1/context/prepare``                 -> the bounded context the
   Server assembles for one request.

The target test and the regression tests are separated from the *stored* test
module source: a test is the target when its body compares a padded status
with the trimmed one, everything else is a regression test.

Usage:

    python3 minimax/context.py
    python3 minimax/context.py --emit-context minimax/change/input-context.md
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pc_client  # noqa: E402
from ingest import resolve_scope_id  # noqa: E402

_VERSION_MARKER = re.compile(r"^版本:\s*(\S+)\s*$", re.MULTILINE)
_VERSION_NUMBER = re.compile(r"(\d+)")

MEMORY_QUERY = "目标测试 失败 待修复"
PREPARE_QUERY = "任务状态 目标测试 待修复"


# --- source records ----------------------------------------------------------


def _record_text(record: dict) -> str:
    """Flatten one Source record into text."""
    content = record.get("content")
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def _metadata(record: dict) -> dict:
    content = record.get("content")
    if isinstance(content, dict) and isinstance(content.get("metadata"), dict):
        return content["metadata"]
    return {}


def _strip_header(text: str) -> str:
    """Remove the ``# source_path:`` / ``# source_role:`` header lines."""
    lines = text.splitlines()
    while lines and lines[0].startswith("# source_"):
        lines.pop(0)
    return "\n".join(lines).lstrip("\n")


def _collect_sources(scope_id: str) -> list[dict]:
    """Read every Source of the Scope and normalize it."""
    collected = []
    for record in pc_client.list_sources(scope_id):
        text = _record_text(record)
        metadata = _metadata(record)
        role = metadata.get("role")
        if not role:
            match = re.search(r"^# source_role: (\S+)$", text, re.MULTILINE)
            role = match.group(1) if match else None
        path = metadata.get("path")
        if not path:
            match = re.search(r"^# source_path: (.+)$", text, re.MULTILINE)
            path = match.group(1).strip() if match else None
        version = metadata.get("version")
        if not version:
            match = _VERSION_MARKER.search(text)
            version = match.group(1) if match else None
        collected.append(
            {
                "source_id": record.get("source_id"),
                "role": role,
                "path": path,
                "version": version,
                "position": record.get("position", 0),
                "body": _strip_header(text),
            }
        )
    return collected


def _version_rank(version: str | None) -> int:
    """Order versions numerically (``v2`` > ``v1``); unknown versions rank lowest."""
    if not version:
        return -1
    match = _VERSION_NUMBER.search(version)
    return int(match.group(1)) if match else -1


def _pick_current(sources: list[dict], role: str) -> dict | None:
    """Pick the current record of one role.

    The specification is selected by version number first (so a re-import
    never shadows the current version), then by position. The code and the
    test module are selected by position, i.e. the most recent import.
    """
    candidates = [s for s in sources if s["role"] == role]
    if not candidates:
        return None
    if role == "spec":
        return max(candidates, key=lambda s: (_version_rank(s["version"]), s["position"]))
    return max(candidates, key=lambda s: s["position"])


# --- test classification -----------------------------------------------------


def _test_functions(test_source: str) -> list[dict]:
    """Parse the stored test module into its test functions."""
    tree = ast.parse(test_source)
    functions = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            segment = ast.get_source_segment(test_source, node) or ""
            literals = [
                item.value
                for item in ast.walk(node)
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            ]
            functions.append({"name": node.name, "source": segment, "literals": literals})
    return functions


def _split_tests(test_source: str) -> tuple[list[dict], list[dict]]:
    """Split the test module into (target tests, regression tests).

    A test is the target when its body compares a padded status literal
    (``" open "``) with the same status without padding (``"open"``).
    """
    functions = _test_functions(test_source)
    all_literals = {literal for function in functions for literal in function["literals"]}
    target, regression = [], []
    for function in functions:
        padded = [
            literal
            for literal in function["literals"]
            if literal != literal.strip() and literal.strip() in all_literals
        ]
        (target if padded else regression).append(function)
    return target, regression


# --- context assembly --------------------------------------------------------


def _memory_states(scope_id: str) -> list[dict]:
    """Read every task state stored in PowerContext (active and superseded).

    Without an explicit ``states`` filter the Server only returns the active
    heads; all four lifecycle states are requested so the previous state stays
    visible next to the current one.
    """
    response = pc_client.request(
        "POST",
        "/v1/atomic-memory/list",
        {
            "scope_id": scope_id,
            "kind": "task-state",
            "states": ["active", "forgotten", "merged", "retired"],
            "limit": 100,
        },
    )
    states = []
    for entry in response.get("items", []):
        artifact = entry.get("artifact") or {}
        states.append(
            {
                "artifact_id": artifact.get("artifact_id"),
                "revision": artifact.get("revision"),
                "kind": entry.get("kind"),
                "text": entry.get("text"),
                "state": entry.get("state"),
            }
        )
    return states


def _current_state(states: list[dict]) -> dict | None:
    """The current state is the newest *active* task-state entry.

    Superseded states stay in the list with state ``forgotten``, so the
    previous state remains visible and distinguishable from the current one.
    """
    task_states = [s for s in states if s.get("kind") == "task-state"]
    if not task_states:
        return None
    active = [s for s in task_states if s.get("state") == "active"]
    pool = active or task_states
    return max(pool, key=lambda s: (s.get("revision") or 0, s.get("artifact_id") or ""))


def build_context(scope_id: str) -> tuple[str, dict]:
    """Assemble the working context out of live queries. Returns (text, facts)."""
    sources = _collect_sources(scope_id)
    spec = _pick_current(sources, "spec")
    code = _pick_current(sources, "code")
    test = _pick_current(sources, "test")
    states = _memory_states(scope_id)
    current_state = _current_state(states)

    target_tests, regression_tests = ([], [])
    if test:
        target_tests, regression_tests = _split_tests(test["body"])

    lines: list[str] = []
    lines.append("# MiniMax 样例工作上下文")
    lines.append("")
    lines.append(f"scope_id: {scope_id}")
    lines.append(f"server:   {pc_client.base_url()}")
    lines.append("")

    # 1) current specification
    lines.append("## 1. 业务规格（当前版本）")
    if spec:
        lines.append(f"source_id: {spec['source_id']}")
        lines.append(f"version:   {spec['version']}")
        lines.append(f"来源:      {spec['path']}")
        lines.append("")
        lines.append(spec["body"].rstrip())
    else:
        lines.append("(未找到规格记录)")
    lines.append("")
    archived = [
        s
        for s in sources
        if s["role"] == "spec" and spec is not None and s["source_id"] != spec["source_id"]
    ]
    if archived:
        lines.append("已归档的旧版本规格：")
        for old in sorted(archived, key=lambda s: (_version_rank(s["version"]), s["position"])):
            lines.append(f"  - {old['source_id']} version={old['version']} 来源={old['path']}")
        lines.append("")

    # 2) related code
    lines.append("## 2. 相关代码")
    if code:
        lines.append(f"source_id: {code['source_id']}")
        lines.append(f"来源:      {code['path']}")
        lines.append("")
        lines.append(code["body"].rstrip())
    else:
        lines.append("(未找到代码记录)")
    lines.append("")

    # 3) target test
    lines.append("## 3. 目标测试")
    if test:
        lines.append(f"source_id: {test['source_id']}")
        lines.append(f"来源:      {test['path']}")
        lines.append("")
        if target_tests:
            for function in target_tests:
                lines.append(function["source"].rstrip())
                lines.append("")
        else:
            lines.append("(未识别出目标测试)")
    else:
        lines.append("(未找到测试记录)")
    lines.append("")

    # 4) regression tests
    lines.append("## 4. 回归测试")
    if test:
        if regression_tests:
            for function in regression_tests:
                lines.append(function["source"].rstrip())
                lines.append("")
        else:
            lines.append("(未识别出回归测试)")
    else:
        lines.append("(未找到测试记录)")
    lines.append("")

    # 5) task state
    lines.append("## 5. 任务状态（PowerContext Memory）")
    if states:
        for state in states:
            if current_state is not None and state is current_state:
                label = "当前状态"
            elif state.get("state") == "forgotten":
                label = "已被取代"
            else:
                label = "历史状态"
            lines.append(
                f"  [{label}] {state['artifact_id']} rev={state['revision']} "
                f"state={state['state']}: {state['text']}"
            )
    else:
        lines.append("(暂无状态记录)")
    lines.append("")

    # 6) the context the Server hands to one model request
    prepared = pc_client.prepare_context(scope_id, PREPARE_QUERY, max_bytes=8000)
    prepared_content = prepared.get("content") or ""
    lines.append("## 6. Server 组装的上下文（/v1/context/prepare）")
    lines.append(f"status: {prepared.get('status')}  content_bytes: {prepared.get('content_bytes')}")
    lines.append("")
    if prepared_content:
        lines.append(prepared_content.rstrip())
    else:
        lines.append("(空)")
    lines.append("")

    text = "\n".join(lines).rstrip() + "\n"
    facts = {
        "scope_id": scope_id,
        "spec": spec,
        "code": code,
        "test": test,
        "archived_specs": archived,
        "target_tests": [f["name"] for f in target_tests],
        "regression_tests": [f["name"] for f in regression_tests],
        "states": states,
        "current_state": current_state,
        "prepared": prepared,
        "prepared_content": prepared_content,
    }
    return text, facts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assemble the MiniMax working context.")
    parser.add_argument(
        "--emit-context",
        metavar="PATH",
        help="write the assembled context to this file as well",
    )
    args = parser.parse_args(argv)

    scope_id = resolve_scope_id()
    text, facts = build_context(scope_id)

    if args.emit_context:
        target = Path(args.emit_context)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        print(f"context written -> {target}")

    print(text)
    print("== summary ==")
    spec = facts["spec"]
    code = facts["code"]
    test = facts["test"]
    print(f"  spec    : {spec['source_id'] if spec else 'MISSING'} version={spec['version'] if spec else '-'}")
    print(f"           path={spec['path'] if spec else '-'}")
    print(f"  code    : {code['source_id'] if code else 'MISSING'}")
    print(f"           path={code['path'] if code else '-'}")
    print(f"  test    : {test['source_id'] if test else 'MISSING'}")
    print(f"           path={test['path'] if test else '-'}")
    print(f"  target  : {', '.join(facts['target_tests']) or 'NONE'}")
    print(f"  regress : {', '.join(facts['regression_tests']) or 'NONE'}")
    for state in facts["states"]:
        label = "当前" if state is facts["current_state"] else "历史"
        print(f"  {label} state  : rev={state['revision']} state={state['state']} — {state['text']}")
    prepared = facts["prepared"]
    used = facts["current_state"] is not None and facts["current_state"]["text"] in facts["prepared_content"]
    print(f"  prepared context: status={prepared.get('status')} 含当前状态={used}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
