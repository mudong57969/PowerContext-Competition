from __future__ import annotations

import asyncio
import json
import random

import pytest
from pydantic import ValidationError
from sqlalchemy import event as sql_event

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import EmbeddingProfile, MemoryEntryInput
from powercontext.builtin.inference import EmbeddingResult
from powercontext.builtin.persistence.oceanbase.topic_memory_index import OceanBaseTopicMemoryVectorIndex
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.records import ArtifactWrite
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    GetMemoryEntryRequest,
    RememberMemoryRequest,
    ReviseMemoryEntryRequest,
    SearchMemoryRequest,
    SearchTopicMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.source_lifecycle import SourceLifecycleError, SourceLifecycleEvent
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import SourceRef


def change(available: bool, sequence: int = 1, reason: str = "evidence changed") -> SourceLifecycleEvent:
    return SourceLifecycleEvent(node_id="origin", revision=7, sequence=sequence, available=available, reason=reason)


@pytest.mark.parametrize(
    "field,value",
    [
        ("node_id", ""),
        ("node_id", " \t"),
        ("node_id", 1),
        ("reason", " "),
        ("available", 0),
        ("available", "false"),
        ("extra", True),
        *((field, value) for field in ("revision", "sequence") for value in (False, True, 0, -1, 1.0, "1")),
    ],
)
def test_event_contract(field: str, value: object) -> None:
    data = change(True).model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        SourceLifecycleEvent.model_validate(data)


async def build(runtime, scope: str):
    scope = (
        await runtime.scopes.create(ScopeDraft(title=scope, summary="lifecycle test", idempotency_key=scope))
    ).scope_id
    service = runtime.lifecycle.for_scope(scope)
    receipt = await runtime.sources.for_scope(scope).capture(
        CaptureSource(source_id="original", content="durable origin", metadata={})
    )
    await service.register_source("origin", receipt.source_ref, revision=7)
    citations = []
    for index in range(3):
        memory = await runtime.memory.for_scope(scope).remember(
            RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text=f"lifecycle evidence {index}"),))
        )
        citation = memory.entry.citation
        await service.register_memory(f"fact-{index}", citation, parents=("origin",))
        citations.append(citation)
    record = await runtime.records.for_scope(scope).create_artifact(
        "topic-memory",
        ArtifactWrite(
            content={
                "title": "lifecycle summary",
                "summary": "lifecycle evidence supported",
                "detail": "lifecycle detail evidence",
            }
        ),
    )
    topic = ArtifactRef(family="topic-memory", artifact_id=record.artifact_id, revision=record.revision)
    await service.register_topic("summary", topic, parents=("fact-0", "fact-1"), policy="any")
    return service, receipt.source_ref, citations, topic, scope


def test_registration_conflicts_and_exact_reference_validation() -> None:
    async def run() -> None:
        async with open_builtin_runtime(BuiltinConfig(database=SQLiteConfig())) as runtime:
            lifecycle, source, citations, topic, scope = await build(runtime, "validation")
            before = (await runtime.memory.for_scope(scope).list()).memory_ref
            await lifecycle.register_source("origin", source, revision=7)
            await lifecycle.register_memory("fact-0", citations[0], parents=("origin",))
            await lifecycle.register_topic("summary", topic, parents=("fact-1", "fact-0"), policy="any")
            assert (await runtime.memory.for_scope(scope).list()).memory_ref == before
            for parents in ((), ("origin", "origin"), ("absent",), ("cycle",)):
                with pytest.raises(SourceLifecycleError):
                    await lifecycle.register_memory("cycle", citations[0], parents=parents)
            with pytest.raises(SourceLifecycleError):
                await lifecycle.register_source("origin", source, revision=8)
            with pytest.raises(SourceLifecycleError):
                await lifecycle.register_memory("fact-0", citations[1], parents=("origin",))
            for revision in (True, 1.0, "7", 0, -2):
                with pytest.raises(SourceLifecycleError):
                    await lifecycle.register_source("invalid-revision", source, revision=revision)
            with pytest.raises(SourceLifecycleError):
                await lifecycle.register_source(
                    "missing-source", SourceRef(source_type=source.source_type, source_id="absent"), revision=7
                )
            with pytest.raises(SourceLifecycleError):
                await lifecycle.register_memory(
                    "missing-memory",
                    citations[0].model_copy(update={"entry_version_id": "absent"}),
                    parents=("origin",),
                )
            with pytest.raises(SourceLifecycleError):
                await lifecycle.register_topic(
                    "missing-topic", topic.model_copy(update={"revision": topic.revision + 20}), parents=("origin",)
                )
            with pytest.raises(SourceLifecycleError):
                await lifecycle.resolve("origin", purpose="other")
            with pytest.raises(SourceLifecycleError):
                await lifecycle.apply(change(False).model_copy(update={"node_id": "fact-0"}))
            await lifecycle.apply(change(False))
            with pytest.raises(SourceLifecycleError):
                await lifecycle.apply(change(False, reason="different identity"))

    asyncio.run(run())


def test_readable_historical_citation_does_not_poison_registration_or_recovery(tmp_path) -> None:
    async def run() -> None:
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'history.db'}"))
        async with open_builtin_runtime(config) as runtime:
            assert runtime.scopes is not None
            scope = (
                await runtime.scopes.create(
                    ScopeDraft(title="history", summary="historical binding", idempotency_key="history")
                )
            ).scope_id
            source = await runtime.sources.for_scope(scope).capture(
                CaptureSource(source_id="original", content="original", metadata={})
            )
            memory = runtime.memory.for_scope(scope)
            first = await memory.remember(
                RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text="old evidence"),))
            )
            assert first.entry is not None
            original = first.entry.citation
            await memory.revise(ReviseMemoryEntryRequest(citation=original, kind="fact", text="current evidence"))
            lifecycle = runtime.lifecycle.for_scope(scope)
            await lifecycle.register_source("origin", source.source_ref, revision=7)
            await lifecycle.register_memory("historical", original, parents=("origin",))
            assert await lifecycle.resolve("historical") == original
            await lifecycle.apply(change(False))
            assert not (await memory.list()).entries
            assert (await memory.get(GetMemoryEntryRequest(citation=original))).entry.text == "old evidence"
        async with open_builtin_runtime(config) as runtime:
            lifecycle = runtime.lifecycle.for_scope(scope)
            assert await lifecycle.resolve("historical", purpose="audit") == original
            await lifecycle.apply(change(True, 2))
            assert (await runtime.memory.for_scope(scope).list()).entries[0].entry.text == "current evidence"
            assert await lifecycle.resolve("historical") == original

    asyncio.run(run())


def test_vector_queries_exclude_withdrawn_topics_before_candidate_limits() -> None:
    class Embedding:
        profile = EmbeddingProfile(profile_id="lifecycle-vectors", model="offline", dimension=2)

        async def embed(self, texts: tuple[str, ...]) -> EmbeddingResult:
            return EmbeddingResult(vectors=tuple((1.0, 0.0) for _ in texts))

    async def run() -> None:
        async with open_builtin_runtime(BuiltinConfig(database=SQLiteConfig()), embedding_model=Embedding()) as runtime:
            lifecycle, _, _, _, scope = await build(runtime, "vectors")
            memory = runtime.memory.for_scope(scope)
            await memory.remember(
                RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text="independent evidence"),))
            )
            await runtime.records.for_scope(scope).create_artifact(
                "topic-memory",
                ArtifactWrite(
                    content={
                        "title": "independent topic",
                        "summary": "independent evidence",
                        "detail": "independent detail",
                    }
                ),
            )
            await lifecycle.apply(change(False))
            # Execute the adapter's relational completeness check on real SQLite
            # projections; this does not exercise OceanBase's native ANN executor.
            vector_index = OceanBaseTopicMemoryVectorIndex(Embedding.profile)
            reference = await lifecycle.resolve("summary", purpose="audit")
            async with runtime.lifecycle.database.transaction() as connection:
                assert await vector_index.vector_complete(connection, scope, reference)
            hits = await memory.search(SearchMemoryRequest(query="evidence", mode="vector", limit=1))
            assert [hit.text for hit in hits.hits] == ["independent evidence"]
            topics = await runtime.topic_memory.for_scope(scope).search(
                SearchTopicMemoryRequest(query="evidence", limit=1)
            )
            assert len(topics.hits) == 1
            assert topics.hits[0].title == "independent topic"
            await lifecycle.apply(change(True, 2))
            assert len(await runtime.topic_memory.for_scope(scope).browse(limit=10)) == 2

    asyncio.run(run())


@pytest.mark.parametrize("recover_on_restart", [False, True])
def test_sqlite_partial_native_failure_retries_without_duplicate_revisions(tmp_path, recover_on_restart: bool) -> None:
    async def run() -> None:
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'lifecycle.db'}"))
        async with open_builtin_runtime(config) as runtime:
            lifecycle, _, citations, topic, scope = await build(runtime, "fault")
            _, _, _, _, independent = await build(runtime, "independent")
            before = (await runtime.memory.for_scope(scope).list()).memory_ref
            assert before is not None
            writes = 0

            def fail_second_write(connection, cursor, statement, parameters, context, executemany):
                nonlocal writes
                if statement.startswith("INSERT INTO pc_artifacts "):
                    writes += 1
                    if writes == 2:
                        message = "injected native SQLite write failure"
                        raise RuntimeError(message)

            engine = runtime.lifecycle.database.engine.sync_engine
            sql_event.listen(engine, "before_cursor_execute", fail_second_write)
            try:
                with pytest.raises(RuntimeError, match="injected native SQLite"):
                    await lifecycle.apply(change(False))
            finally:
                sql_event.remove(engine, "before_cursor_execute", fail_second_write)
            partial = await runtime.memory.for_scope(scope).list(include_inactive=True)
            assert partial.memory_ref is not None
            assert partial.memory_ref.revision == before.revision + 1
            assert sum(item.state == "inactive" for item in partial.entries) == 1
            if not recover_on_restart:
                assert await lifecycle.apply(change(False)) == []
        async with open_builtin_runtime(config) as runtime:
            lifecycle = runtime.lifecycle.for_scope(scope)
            page = await runtime.memory.for_scope(scope).list(include_inactive=True)
            assert page.memory_ref is not None
            assert all(item.state == "inactive" for item in page.entries)
            assert page.memory_ref.revision == before.revision + 3
            assert await lifecycle.apply(change(False)) == []
            assert (await runtime.memory.for_scope(scope).list(include_inactive=True)).memory_ref == page.memory_ref
            assert len((await runtime.memory.for_scope(independent).list()).entries) == 3
            assert not (
                await runtime.topic_memory.for_scope(scope).search(SearchTopicMemoryRequest(query="lifecycle"))
            ).hits
            assert (
                await runtime.topic_memory.for_scope(independent).search(SearchTopicMemoryRequest(query="lifecycle"))
            ).hits
            assert not await runtime.topic_memory.for_scope(scope).browse(limit=10)
            assert await lifecycle.resolve("summary", purpose="audit") == topic
            for citation in citations:
                assert (
                    await runtime.memory.for_scope(scope).get(GetMemoryEntryRequest(citation=citation))
                ).entry.text.startswith("lifecycle")
            await lifecycle.apply(change(True, 2))
            restored = (await runtime.memory.for_scope(scope).list()).memory_ref
            assert restored is not None
            assert restored.revision == before.revision + 6
            assert (
                len(
                    (
                        await runtime.memory.for_scope(scope).search(SearchMemoryRequest(query="lifecycle", mode="fts"))
                    ).hits
                )
                == 3
            )
            assert await lifecycle.resolve("fact-0") == citations[0]
            assert (await runtime.topic_memory.for_scope(scope).search(SearchTopicMemoryRequest(query="detail"))).hits
            await lifecycle.apply(change(True, 2))
            assert (await runtime.memory.for_scope(scope).list()).memory_ref == restored

    asyncio.run(run())


@pytest.mark.parametrize("restore", [False, True])
@pytest.mark.parametrize("restart", [False, True])
def test_completion_marker_failure_replays_without_native_revisions(tmp_path, restore: bool, restart: bool) -> None:
    async def run() -> None:
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'completion.db'}"))
        async with open_builtin_runtime(config) as runtime:
            lifecycle, _, _, _, scope = await build(runtime, "completion")
            if restore:
                await lifecycle.apply(change(False))
            before = (await runtime.memory.for_scope(scope).list(include_inactive=True)).memory_ref
            current_event = change(restore, 2 if restore else 1)

            def fail_completion(connection, cursor, statement, parameters, context, executemany):
                if statement.startswith("UPDATE pc_source_lifecycle_graphs "):
                    graph = json.loads(parameters[0])
                    if not graph["pending"]:
                        message = "injected completion marker failure"
                        raise RuntimeError(message)

            engine = runtime.lifecycle.database.engine.sync_engine
            sql_event.listen(engine, "before_cursor_execute", fail_completion)
            try:
                with pytest.raises(RuntimeError, match="completion marker"):
                    await lifecycle.apply(current_event)
            finally:
                sql_event.remove(engine, "before_cursor_execute", fail_completion)
            complete = await runtime.memory.for_scope(scope).list(include_inactive=True)
            assert before is not None and complete.memory_ref is not None
            assert complete.memory_ref.revision == before.revision + 3
            assert all((record.state == "active") == restore for record in complete.entries)
            if not restart:
                await lifecycle.apply(current_event)
                assert (
                    await runtime.memory.for_scope(scope).list(include_inactive=True)
                ).memory_ref == complete.memory_ref
        async with open_builtin_runtime(config) as runtime:
            lifecycle = runtime.lifecycle.for_scope(scope)
            active = await lifecycle.apply(current_event)
            assert bool(active) == restore
            assert (await runtime.memory.for_scope(scope).list(include_inactive=True)).memory_ref == complete.memory_ref
            assert bool(await runtime.topic_memory.for_scope(scope).browse(limit=10)) == restore

    asyncio.run(run())


def test_newer_event_finishes_interrupted_restore_before_withdrawing_again(tmp_path) -> None:
    async def run() -> None:
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'restore.db'}"))
        async with open_builtin_runtime(config) as runtime:
            lifecycle, _, _, _, scope = await build(runtime, "restore")
            await lifecycle.apply(change(False))
            before = (await runtime.memory.for_scope(scope).list(include_inactive=True)).memory_ref
            writes = 0

            def fail_restore(connection, cursor, statement, parameters, context, executemany):
                nonlocal writes
                if statement.startswith("INSERT INTO pc_artifacts "):
                    writes += 1
                    if writes == 2:
                        message = "injected restore failure"
                        raise RuntimeError(message)

            engine = runtime.lifecycle.database.engine.sync_engine
            sql_event.listen(engine, "before_cursor_execute", fail_restore)
            try:
                with pytest.raises(RuntimeError, match="restore failure"):
                    await lifecycle.apply(change(True, 2))
            finally:
                sql_event.remove(engine, "before_cursor_execute", fail_restore)
            assert await lifecycle.apply(change(False, 3)) == []
            final = await runtime.memory.for_scope(scope).list(include_inactive=True)
            assert before is not None and final.memory_ref is not None
            assert final.memory_ref.revision == before.revision + 6
            assert all(record.state == "inactive" for record in final.entries)
            assert not await runtime.topic_memory.for_scope(scope).browse(limit=10)
            with pytest.raises(SourceLifecycleError):
                await lifecycle.apply(change(True, 2))
            await lifecycle.apply(change(False, 3))
            assert (await runtime.memory.for_scope(scope).list(include_inactive=True)).memory_ref == final.memory_ref

    asyncio.run(run())


async def assert_graph(runtime, scope, lifecycle, references, expected) -> None:
    states = {
        record.entry.text.split()[0]: record.state == "active"
        for record in (await runtime.memory.for_scope(scope).list(include_inactive=True)).entries
    }
    for node, reference in references.items():
        assert await lifecycle.resolve(node, purpose="audit") == reference
        if expected[node]:
            assert await lifecycle.resolve(node) == reference
        else:
            with pytest.raises(SourceLifecycleError):
                await lifecycle.resolve(node)
        if node in states:
            assert states[node] == expected[node]
        elif isinstance(reference, ArtifactRef):
            page = await runtime.topic_memory.for_scope(scope).search(SearchTopicMemoryRequest(query=node))
            assert bool(page.hits) == expected[node]


@pytest.mark.parametrize("seed", [19, 73])
def test_varied_dags_recompute_all_descendants_and_isolate_same_named_scopes(seed: int) -> None:
    async def run() -> None:
        rng = random.Random(seed)  # noqa: S311 -- reproducible test data, not security
        async with open_builtin_runtime(BuiltinConfig(database=SQLiteConfig())) as runtime:
            assert runtime.scopes is not None
            bindings = {}
            for label in ("left", "right"):
                scope = (
                    await runtime.scopes.create(ScopeDraft(title=label, summary="varied DAG", idempotency_key=label))
                ).scope_id
                lifecycle = runtime.lifecycle.for_scope(scope)
                references = {}
                dependencies = {}
                roots = [f"origin{index}" for index in range(3)]
                for root in roots:
                    receipt = await runtime.sources.for_scope(scope).capture(
                        CaptureSource(source_id=root, content=root, metadata={})
                    )
                    await lifecycle.register_source(root, receipt.source_ref, revision=11)
                    references[root] = receipt.source_ref
                for index in range(rng.randint(8, 12)):
                    node = f"evidence{index}"
                    parents = tuple(rng.sample(list(references), rng.randint(1, min(3, len(references)))))
                    policy = rng.choice(("all", "any"))
                    if index % 3:
                        result = await runtime.memory.for_scope(scope).remember(
                            RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text=f"{node} evidence"),))
                        )
                        assert result.entry is not None
                        reference = result.entry.citation
                        await lifecycle.register_memory(node, reference, parents=parents, policy=policy)
                    else:
                        artifact = await runtime.records.for_scope(scope).create_artifact(
                            "topic-memory", ArtifactWrite(content={"title": node, "summary": node, "detail": node})
                        )
                        reference = ArtifactRef(
                            family="topic-memory", artifact_id=artifact.artifact_id, revision=artifact.revision
                        )
                        await lifecycle.register_topic(node, reference, parents=parents, policy=policy)
                    references[node] = reference
                    dependencies[node] = (parents, policy)
                bindings[label] = (scope, lifecycle, references, dependencies)
            scope, lifecycle, references, dependencies = bindings["left"]
            independent_scope, independent, independent_refs, _ = bindings["right"]
            independent_head = (await runtime.memory.for_scope(independent_scope).list()).memory_ref
            source_states = dict.fromkeys(roots, True)
            sequences = dict.fromkeys(roots, 0)
            for root, available in [(root, False) for root in roots] + [(root, True) for root in reversed(roots)]:
                source_states[root] = available
                sequences[root] += 1
                expected = source_states.copy()
                for node, (parents, policy) in dependencies.items():
                    supported = sum(expected[parent] for parent in parents)
                    expected[node] = supported == len(parents) if policy == "all" else supported > 0
                active = await lifecycle.apply(
                    SourceLifecycleEvent(
                        node_id=root, revision=11, sequence=sequences[root], available=available, reason="varied graph"
                    )
                )
                assert active == sorted(node for node, state in expected.items() if state)
                await assert_graph(runtime, scope, lifecycle, references, expected)
                assert (await runtime.memory.for_scope(independent_scope).list()).memory_ref == independent_head
                for node, reference in independent_refs.items():
                    assert await independent.resolve(node) == reference

    asyncio.run(run())
