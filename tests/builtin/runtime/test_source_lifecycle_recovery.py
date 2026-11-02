from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import delete, insert, select, update
from sqlalchemy import event as sql_event
from sqlalchemy.engine import Engine

from powercontext.builtin.artifacts.memory import CapabilityNotSupportedError, MemoryEntryInput
from powercontext.builtin.persistence.source_lifecycle import LIFECYCLE_GRAPHS
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.persistence.tables import MEMORY_ENTRY_VERSIONS_TABLE
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    GetMemoryEntryRequest,
    RememberMemoryRequest,
    SearchMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.config import RuntimeConfig
from powercontext.builtin.runtime.source_lifecycle import SourceLifecycleError
from tests.builtin.runtime.test_source_lifecycle import build, change


def config_for(tmp_path) -> BuiltinConfig:
    return BuiltinConfig(
        database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'recovery.db'}"),
        runtime=RuntimeConfig(memory_compaction_enabled=True, memory_compaction_min_tombstone_revisions=0),
    )


async def age_tombstones(runtime, scope) -> None:
    await runtime.memory.for_scope(scope).remember(
        RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text="unmanaged later revision"),))
    )


async def simulate_pre_fix_compaction(runtime, scope):
    # Fresh test database only: emulate a legacy compactor that had no lifecycle guard.
    database = runtime.lifecycle.database
    async with database.transaction() as connection:
        graph = await connection.scalar(select(LIFECYCLE_GRAPHS.c.graph).where(LIFECYCLE_GRAPHS.c.scope_id == scope))
        await connection.execute(delete(LIFECYCLE_GRAPHS).where(LIFECYCLE_GRAPHS.c.scope_id == scope))
    try:
        result = await runtime.memory.for_scope(scope).compact()
    finally:
        async with database.transaction() as connection:
            await connection.execute(insert(LIFECYCLE_GRAPHS).values(scope_id=scope, graph=graph))
    return result


def test_native_compaction_refuses_managed_tombstones_and_restore_still_works(tmp_path) -> None:
    async def run() -> None:
        async with open_builtin_runtime(config_for(tmp_path)) as runtime:
            lifecycle, _, citations, _, scope = await build(runtime, "protected")
            await lifecycle.apply(change(False))
            await age_tombstones(runtime, scope)
            memory = runtime.memory.for_scope(scope)
            before = await memory.list(include_inactive=True)
            with pytest.raises(CapabilityNotSupportedError, match="compaction-lifecycle-conflict"):
                await memory.compact()
            assert (await memory.list(include_inactive=True)).memory_ref == before.memory_ref
            await lifecycle.apply(change(True, 2))
            restored = await memory.list(include_inactive=True)
            assert len(restored.entries) == 4
            assert all(record.state == "active" for record in restored.entries)
            hits = await memory.search(SearchMemoryRequest(query="lifecycle", mode="fts"))
            assert len(hits.hits) == 3
            for index, citation in enumerate(citations):
                assert (
                    await memory.get(GetMemoryEntryRequest(citation=citation))
                ).entry.text == f"lifecycle evidence {index}"
            complete = (await memory.list()).memory_ref
            for _ in range(3):
                await lifecycle.apply(change(True, 2))
            assert (await memory.list()).memory_ref == complete

    asyncio.run(run())


@pytest.mark.parametrize("physical_loss", [False, True])
def test_legacy_missing_binding_is_auditable_pending_and_cannot_block_healthy_scope(
    tmp_path, physical_loss: bool
) -> None:
    async def run() -> None:
        config = config_for(tmp_path)
        async with open_builtin_runtime(config) as runtime:
            lifecycle, _, citations, _, scope = await build(runtime, "damaged")
            healthy, _, _, _, healthy_scope = await build(runtime, "healthy")
            await lifecycle.apply(change(False))
            await age_tombstones(runtime, scope)
            result = await simulate_pre_fix_compaction(runtime, scope)
            assert citations[0].entry_id in result.entry_ids
            memory = runtime.memory.for_scope(scope)
            assert not any(
                record.entry.entry_id == citations[0].entry_id
                for record in (await memory.list(include_inactive=True)).entries
            )
            missing_head = (await memory.list(include_inactive=True)).memory_ref
            assert (await memory.get(GetMemoryEntryRequest(citation=citations[0]))).entry.text == "lifecycle evidence 0"
            if physical_loss:
                async with runtime.lifecycle.database.transaction() as connection:
                    await connection.execute(
                        delete(MEMORY_ENTRY_VERSIONS_TABLE).where(
                            MEMORY_ENTRY_VERSIONS_TABLE.c.scope_id == scope,
                            MEMORY_ENTRY_VERSIONS_TABLE.c.entry_version_id == citations[0].entry_version_id,
                        )
                    )
            with pytest.raises(SourceLifecycleError):
                await lifecycle.apply(change(True, 2))
            status = await lifecycle.status()
            assert status["pending"] is True
            assert status["fault"]["code"] == (
                "unreadable-reference" if physical_loss else "bound-memory-entry-missing"
            )
            if physical_loss:
                with pytest.raises(SourceLifecycleError, match="unreadable-reference"):
                    await lifecycle.resolve("fact-0", purpose="audit")
            else:
                assert await lifecycle.resolve("fact-0", purpose="audit") == citations[0]
            assert not await runtime.topic_memory.for_scope(scope).browse(limit=10)
            assert await healthy.resolve("fact-0")
        async with open_builtin_runtime(config) as runtime:
            lifecycle = runtime.lifecycle.for_scope(scope)
            assert await lifecycle.status() == status
            for _ in range(2):
                with pytest.raises(SourceLifecycleError):
                    await lifecycle.apply(change(True, 2))
            assert (await runtime.memory.for_scope(scope).list(include_inactive=True)).memory_ref == missing_head
            with pytest.raises(SourceLifecycleError):
                await lifecycle.resolve("fact-0")
            assert (await lifecycle.status())["pending"] is True
            healthy = runtime.lifecycle.for_scope(healthy_scope)
            await healthy.apply(change(False))
            await healthy.apply(change(True, 2))
            assert len((await runtime.memory.for_scope(healthy_scope).list()).entries) == 3

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["memory", "topic"])
def test_duplicate_native_bindings_are_rejected_but_same_registration_is_idempotent(kind: str) -> None:
    async def run() -> None:
        async with open_builtin_runtime(BuiltinConfig(database=SQLiteConfig())) as runtime:
            lifecycle, _, citations, topic, scope = await build(runtime, "duplicate")
            source = await runtime.sources.for_scope(scope).capture(
                CaptureSource(source_id="independent-origin", content="independent evidence", metadata={})
            )
            await lifecycle.register_source("independent", source.source_ref, revision=7)
            register = lifecycle.register_memory if kind == "memory" else lifecycle.register_topic
            reference = citations[0] if kind == "memory" else topic
            node = "fact-0" if kind == "memory" else "summary"
            parents = ("origin",) if kind == "memory" else ("fact-0", "fact-1")
            policy = "all" if kind == "memory" else "any"
            before = (await runtime.memory.for_scope(scope).list()).memory_ref
            await register(node, reference, parents=parents, policy=policy)
            for alias_parents in (("independent",), parents):
                with pytest.raises(SourceLifecycleError, match="duplicate-native-binding"):
                    await register("alias", reference, parents=alias_parents, policy=policy)
            assert (await runtime.memory.for_scope(scope).list()).memory_ref == before
            await lifecycle.apply(change(False))
            with pytest.raises(SourceLifecycleError):
                await lifecycle.resolve(node)
            assert await lifecycle.resolve(node, purpose="audit") == reference
            assert not await runtime.topic_memory.for_scope(scope).browse(limit=10)
            # Native identities are local to their scope, not global aliases.
            await build(runtime, "other-scope")

    asyncio.run(run())


def test_startup_transient_failure_keeps_pending_then_same_event_completes(tmp_path) -> None:
    async def run() -> None:
        config = config_for(tmp_path)
        async with open_builtin_runtime(config) as runtime:
            lifecycle, _, _, _, scope = await build(runtime, "retry")
            _, _, _, _, healthy_scope = await build(runtime, "other")
            before = (await runtime.memory.for_scope(scope).list()).memory_ref

            def fail_native(connection, cursor, statement, parameters, context, executemany):
                if statement.startswith("INSERT INTO pc_artifacts "):
                    message = "temporary native write failure"
                    raise RuntimeError(message)

            engine = runtime.lifecycle.database.engine.sync_engine
            sql_event.listen(engine, "before_cursor_execute", fail_native)
            try:
                with pytest.raises(RuntimeError, match="temporary native"):
                    await lifecycle.apply(change(False))
            finally:
                sql_event.remove(engine, "before_cursor_execute", fail_native)
        sql_event.listen(Engine, "before_cursor_execute", fail_native)
        try:
            async with open_builtin_runtime(config) as runtime:
                lifecycle = runtime.lifecycle.for_scope(scope)
                assert (await lifecycle.status()) == {"pending": True, "fault": None}
                assert await runtime.lifecycle.for_scope(healthy_scope).resolve("fact-0")
                sql_event.remove(Engine, "before_cursor_execute", fail_native)
                assert await lifecycle.apply(change(False)) == []
                assert await lifecycle.status() == {"pending": False, "fault": None}
                complete = (await runtime.memory.for_scope(scope).list(include_inactive=True)).memory_ref
                assert before is not None and complete is not None
                assert complete.revision == before.revision + 3
                for _ in range(3):
                    await lifecycle.apply(change(False))
                assert (await runtime.memory.for_scope(scope).list(include_inactive=True)).memory_ref == complete
        finally:
            if sql_event.contains(Engine, "before_cursor_execute", fail_native):
                sql_event.remove(Engine, "before_cursor_execute", fail_native)

    asyncio.run(run())


def test_legacy_alias_graph_is_quarantined_on_restart(tmp_path) -> None:
    async def run() -> None:
        config = config_for(tmp_path)
        async with open_builtin_runtime(config) as runtime:
            _, _, citations, _, scope = await build(runtime, "legacy-alias")
            async with runtime.lifecycle.database.transaction() as connection:
                value = await connection.scalar(
                    select(LIFECYCLE_GRAPHS.c.graph).where(LIFECYCLE_GRAPHS.c.scope_id == scope)
                )
                assert isinstance(value, str)
                graph = json.loads(value)
                graph["nodes"]["alias"] = graph["nodes"]["fact-0"]
                await connection.execute(
                    update(LIFECYCLE_GRAPHS).where(LIFECYCLE_GRAPHS.c.scope_id == scope).values(graph=json.dumps(graph))
                )
        async with open_builtin_runtime(config) as runtime:
            lifecycle = runtime.lifecycle.for_scope(scope)
            status = await lifecycle.status()
            assert status["pending"] is True
            assert status["fault"] is not None
            assert status["fault"]["code"] == "duplicate-native-binding"
            with pytest.raises(SourceLifecycleError, match="duplicate-native-binding"):
                await lifecycle.resolve("fact-0")
            assert await lifecycle.resolve("fact-0", purpose="audit") == citations[0]

    asyncio.run(run())
