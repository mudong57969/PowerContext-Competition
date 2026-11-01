"""Additional real-worker thresholds using the unchanged licensed public provider."""

import asyncio
import importlib
import sqlite3

import pytest

from powercontext.builtin.artifacts.topic_memory import TOPIC_MEMORY_SOURCE_WINDOW_BINDING
from powercontext.builtin.runtime import open_builtin_runtime
from powercontext.builtin.sources import SourceCursor

checks = importlib.import_module("competition.challenges.processing-01-count-trigger.acceptance.checks")


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["memory", "topic-memory"])
@pytest.mark.parametrize("threshold", [1, 5])
async def test_native_count_window_restart_and_exact_reads(tmp_path, monkeypatch, family, threshold):
    prefix = family.replace("-", "_")
    window_field = "source_window_limit" if family == "memory" else "topic_memory_source_window_limit"
    with checks.provider(monkeypatch) as server:
        settings = checks.config(
            tmp_path / "native-count.db",
            server,
            families=(family,),
            **{f"{prefix}_source_count_threshold": threshold, window_field: 2},
        )
        async with open_builtin_runtime(settings) as runtime:
            sid = await checks.scope(runtime)
            receipts = await checks.capture(runtime, sid, checks.messages()[: threshold - 1])
            await checks.stay_refs(runtime, sid, family, set())
        # Persist inputs below the gate, not just already-generated output.
        async with open_builtin_runtime(settings) as runtime:
            await checks.stay_refs(runtime, sid, family, set())
            receipts += await checks.capture(runtime, sid, checks.messages()[threshold - 1 : threshold])
            consumed = min(threshold, 2) if family == "memory" else threshold
            expected = checks.receipt_refs(receipts[:consumed])
            await checks.wait_refs(runtime, sid, family, expected)
            await checks.capture(runtime, sid, checks.messages()[:threshold])
            await checks.stay_refs(runtime, sid, family, expected)
            await checks.check_reads(runtime, sid, family, expected)
        async with open_builtin_runtime(settings) as runtime:
            await checks.stay_refs(runtime, sid, family, expected)
            await checks.check_reads(runtime, sid, family, expected)
            if family == "memory" and threshold == 5:
                await runtime.memory.for_scope(sid).flush()
                await checks.wait_refs(runtime, sid, family, checks.receipt_refs(receipts[:4]))


@pytest.mark.asyncio
async def test_partial_topic_wave_resumes_below_threshold_after_storage_failure(tmp_path, monkeypatch):
    database = tmp_path / "partial-topic.db"
    with checks.provider(monkeypatch) as server:
        settings = checks.config(
            database,
            server,
            families=("topic-memory",),
            topic_memory_source_count_threshold=3,
            topic_memory_source_window_limit=1,
        )
        async with open_builtin_runtime(settings) as runtime:
            sid = await checks.scope(runtime)
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "CREATE TRIGGER interrupt_second_window BEFORE INSERT ON pc_artifacts "
                    "WHEN NEW.family = 'topic-memory' AND "
                    "(SELECT count(*) FROM pc_artifacts WHERE family = 'topic-memory') >= 1 "
                    "BEGIN SELECT RAISE(ABORT, 'partial wave storage failure'); END"
                )
            receipts = await checks.capture(runtime, sid, checks.messages()[:3])
            first = checks.receipt_refs(receipts[:1])
            await checks.wait_refs(runtime, sid, "topic-memory", first)
            supervisor = runtime.artifact_processing_supervisor
            assert supervisor is not None
            async with asyncio.timeout(30):
                while not supervisor.family_status["topic-memory"]["failed"]:  # noqa: ASYNC110 - bounded native-worker observation
                    await asyncio.sleep(0.1)
            await checks.stay_refs(runtime, sid, "topic-memory", first)
            with sqlite3.connect(database) as connection:
                row = connection.execute(
                    "SELECT cursor FROM pc_source_cursors WHERE scope_id = ? AND binding_name = ?",
                    (sid, TOPIC_MEMORY_SOURCE_WINDOW_BINDING),
                ).fetchone()
            assert SourceCursor.model_validate_json(row[0]).sequence == receipts[0].sequence
        with sqlite3.connect(database) as connection:
            connection.execute("DROP TRIGGER interrupt_second_window")
        async with open_builtin_runtime(settings) as runtime:
            await checks.wait_refs(runtime, sid, "topic-memory", checks.receipt_refs(receipts))
            await checks.check_reads(runtime, sid, "topic-memory", checks.receipt_refs(receipts))
            await checks.stay_refs(runtime, sid, "topic-memory", checks.receipt_refs(receipts))
