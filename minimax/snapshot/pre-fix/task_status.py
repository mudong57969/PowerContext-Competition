"""Minimal business sample for the MiniMax track.

A small task board backed by a fixed set of records. The business rule is
"filter records by status":

* a legal status (``open`` / ``closed``) selects exactly the records carrying
  that status;
* omitting the status returns every record.

This module keeps the original behaviour on purpose. Status values are
compared verbatim, so surrounding whitespace is *not* stripped yet. The
whitespace gap is captured by the target test in ``test_task_status.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

#: Status values the board considers legal.
LEGAL_STATUSES = ("open", "closed")


@dataclass(frozen=True)
class TaskRecord:
    """A single task row on the board."""

    task_id: str
    title: str
    status: str


#: The fixed record set the sample operates on.
RECORDS: tuple[TaskRecord, ...] = (
    TaskRecord("T-001", "Rebuild pricing index", "open"),
    TaskRecord("T-002", "Rotate signing keys", "open"),
    TaskRecord("T-003", "Archive Q3 receipts", "closed"),
    TaskRecord("T-004", "Patch checkout timeout", "open"),
    TaskRecord("T-005", "Retire legacy endpoint", "closed"),
)


def list_tasks(status: Optional[str] = None) -> list[TaskRecord]:
    """Return the records matching ``status``.

    ``status=None`` returns every record. Any other value is compared with
    ``==`` against the status of each record, so only the exact status string
    matches.

    The comparison is verbatim: ``" open "`` does not match ``"open"``.
    """
    if status is None:
        return list(RECORDS)
    return [record for record in RECORDS if record.status == status]
