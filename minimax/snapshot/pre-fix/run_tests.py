"""Dependency-free test runner for the MiniMax sample.

`pytest` is the normal runner for this repository, but the competition
environment has no guaranteed pytest install and the sample must stay
dependency-free. This runner executes the same ``test_*`` functions with the
standard library only.

Usage:

    python3 minimax/run_tests.py

Exit code is ``0`` when every test passes and ``1`` when at least one test
fails, matching the pytest convention.
"""

from __future__ import annotations

import importlib.util
import sys
import traceback
from pathlib import Path
from types import ModuleType

HERE = Path(__file__).resolve().parent
TEST_MODULE = HERE / "test_task_status.py"


def load_test_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("test_task_status", TEST_MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load test module: {TEST_MODULE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    module = load_test_module()
    tests = sorted(
        (name for name in dir(module) if name.startswith("test_")),
        key=lambda name: getattr(module, name).__code__.co_firstlineno,
    )

    failures: list[tuple[str, str]] = []
    for name in tests:
        test = getattr(module, name)
        try:
            test()
        except Exception:  # noqa: BLE001 - report every failure kind
            detail = traceback.format_exc()
            failures.append((name, detail))
            print(f"FAIL {name}")
        else:
            print(f"PASS {name}")

    total = len(tests)
    print(f"\n{total - len(failures)} passed, {len(failures)} failed, {total} total")
    for name, detail in failures:
        print(f"\n=== {name} ===\n{detail}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
