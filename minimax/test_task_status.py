"""Tests for the MiniMax task-status sample.

The module is written so it runs both under pytest (``pytest minimax``) and
under the dependency-free runner in ``run_tests.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from task_status import RECORDS, TaskRecord, list_tasks  # noqa: E402


# --- regression: existing behaviour that must keep working -------------------


def test_list_tasks_without_status_returns_every_record() -> None:
    """Regression: omitting the status returns the full record set."""
    result = list_tasks()

    assert [record.task_id for record in result] == [
        "T-001",
        "T-002",
        "T-003",
        "T-004",
        "T-005",
    ]
    assert result == list(RECORDS)


def test_list_tasks_with_open_status_returns_only_open_records() -> None:
    """Regression: a legal status selects exactly the matching records."""
    result = list_tasks("open")

    assert result == [
        TaskRecord("T-001", "Rebuild pricing index", "open"),
        TaskRecord("T-002", "Rotate signing keys", "open"),
        TaskRecord("T-004", "Patch checkout timeout", "open"),
    ]
    assert all(record.status == "open" for record in result)


def test_list_tasks_with_closed_status_returns_only_closed_records() -> None:
    """Regression: the other legal status behaves the same way."""
    result = list_tasks("closed")

    assert result == [
        TaskRecord("T-003", "Archive Q3 receipts", "closed"),
        TaskRecord("T-005", "Retire legacy endpoint", "closed"),
    ]
    assert all(record.status == "closed" for record in result)


def test_list_tasks_returns_a_new_list_each_call() -> None:
    """Regression: callers cannot mutate the shared record set."""
    first = list_tasks()
    first.clear()

    assert len(list_tasks()) == len(RECORDS)


# --- target: whitespace handling is not implemented yet ----------------------


def test_status_with_surrounding_whitespace_matches_trimmed_status() -> None:
    """Target: ``" open "`` must select the same records as ``"open"``.

    This currently fails: the comparison is verbatim, so ``" open "`` selects
    nothing. Fixing it is intentionally out of scope for this step.
    """
    assert list_tasks(" open ") == list_tasks("open")
