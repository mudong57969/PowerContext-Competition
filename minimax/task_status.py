"""Minimal business sample for the MiniMax track.

A small task board backed by a fixed set of records. The business rule is
"filter records by status":

* a legal status (``open`` / ``closed``) selects exactly the records carrying
  that status;
* omitting the status returns every record.

This module implements the current business specification (``SPEC.md``):
leading and trailing whitespace of the *status argument* is ignored, so
``" open "`` selects exactly the same records as ``"open"``. The whitespace
rule is covered by the target test in ``test_task_status.py``.
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

    ``status=None`` returns every record. Any other value is normalised by
    stripping leading and trailing whitespace, then compared with ``==``
    against the status of each record, so ``" open "`` matches ``"open"``.

    The normalisation applies to the argument only: the ``status`` field of
    the returned records is never rewritten.
    """
    if status is None:
        return list(RECORDS)
    normalized = status.strip()
    return [record for record in RECORDS if record.status == normalized]
