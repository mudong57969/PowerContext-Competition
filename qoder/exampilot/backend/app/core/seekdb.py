"""Embedded seekdb lifecycle and connection helpers.

seekdb is an embedded database engine (OceanBase) accessed in-process through
the ``pylibseekdb`` binding. One instance is opened per backend process; SQL
access uses pymysql over the engine's local Unix socket.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pymysql

log = logging.getLogger("exampilot.seekdb")


class SeekDBUnavailableError(RuntimeError):
    pass


class SeekDBEngine:
    """Owns one embedded seekdb instance and hands out pymysql connections."""

    def __init__(self, data_dir: str, database: str = "test") -> None:
        self.data_dir = data_dir
        self.database = database
        self._instance: Any = None
        self._lock = threading.Lock()

    def start(self) -> None:
        import pylibseekdb

        path = Path(self.data_dir).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        self._instance = pylibseekdb.open(str(path))
        options = self._instance.connection_options()
        log.info(
            "seekdb instance started at %s, options=%s",
            path,
            {k: v for k, v in options.items()},
        )

    def close(self) -> None:
        if self._instance is not None:
            self._instance.close()
            self._instance = None

    @contextmanager
    def connect(self) -> Iterator[pymysql.Connection]:
        if self._instance is None:
            raise SeekDBUnavailableError("seekdb instance is not started")
        with self._lock:
            options = dict(self._instance.connection_options())
        options.setdefault("connect_timeout", 15)
        options.setdefault("read_timeout", 60)
        options.setdefault("write_timeout", 60)
        conn = pymysql.connect(
            **options, database=self.database, charset="utf8mb4", autocommit=False
        )
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


_instance: SeekDBEngine | None = None
_instance_lock = threading.Lock()


def configure(data_dir: str, database: str = "test") -> SeekDBEngine:
    """Create (and start) the process-wide seekdb engine."""
    global _instance
    with _instance_lock:
        if _instance is not None:
            _instance.close()
        _instance = SeekDBEngine(data_dir, database)
        _instance.start()
        return _instance


def get_engine() -> SeekDBEngine:
    if _instance is None:
        raise SeekDBUnavailableError(
            "seekdb engine is not configured; call configure() first"
        )
    return _instance
