from __future__ import annotations

import asyncio
import importlib.util
import json
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import Engine, event
from sqlalchemy.dialects import mysql
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import CapabilityNotSupportedError, EmbeddingProfile, MemorySearchRequest
from powercontext.builtin.persistence.seekdb.memory_index import SeekDBMemoryIndex
from powercontext.builtin.tags import TagFilter

PROFILE = EmbeddingProfile(profile_id="test", model="offline", dimension=3, distance="l2", normalization="unit")
HEAD = ArtifactRef(family="memory", artifact_id="memory-a", revision=9)


def _request(**changes) -> MemorySearchRequest:
    return MemorySearchRequest.model_validate({
        "query": "alpha ' OR 1=1",
        "analyzed_query": "alpha",
        "mode": "hybrid",
        "memories": (HEAD,),
        "candidate_limit": 40,
        "embedding_profile": PROFILE,
        "query_vector": (1.0, 0.0, 0.0),
        **changes,
    })


def _row(channel: str, entry: str, **changes):
    return {
        "channel": channel,
        "memory_artifact_id": HEAD.artifact_id,
        "head_revision": 1,
        "entry_id": entry,
        "entry_version_id": "version-" + entry,
        "text": "exact " + entry,
        "distance": None if channel == "fts" else 0.25,
        **changes,
    }


@pytest.mark.parametrize(
    "tag_filter",
    [None, TagFilter(tags=("selected",)), TagFilter(tags=("one", "two"), match="any"), TagFilter(tags=("one", "two"))],
)
def test_hybrid_executes_one_parameterized_candidate_query_and_preserves_channels(tag_filter):
    async def scenario():
        index = SeekDBMemoryIndex(PROFILE)
        connection = MagicMock(spec=AsyncConnection)
        connection.execute = AsyncMock()
        connection.execute.return_value = MagicMock()
        connection.execute.return_value.mappings.return_value.all.return_value = [
            _row("fts", "b"),
            _row("fts", "a"),
            _row("vector", "a"),
            _row("vector", "c"),
        ]
        index.vector.vector_complete = AsyncMock(return_value=True)
        result = await index.search(cast(AsyncConnection, connection), "scope-a", _request(tag_filter=tag_filter))
        connection.execute.assert_awaited_once()
        statement, parameters = connection.execute.call_args.args
        sql = str(statement.compile(dialect=mysql.dialect()))
        assert "UNION ALL" in sql
        assert sql.count("LIMIT") == 2
        assert "MATCH" in sql and "AGAINST" in sql and "l2_distance" in sql
        assert "OR 1=1" not in sql
        assert parameters["scope_id"] == "scope-a"
        assert parameters["memory_artifact_ids"] == (HEAD.artifact_id,)
        assert parameters["candidate_limit"] == 40
        assert parameters["query"] == "alpha"
        assert "head_revision =" not in sql
        if tag_filter is not None:
            assert sql.count("FROM pc_artifact_tags") == 2
            assert parameters["tag_minimum"] == (len(tag_filter.keys) if tag_filter.match == "all" else 1)
            assert sql.index("FROM pc_artifact_tags") < sql.index("LIMIT")
        assert [hit.entry_id for hit in result.fts] == ["b", "a"]
        assert [hit.entry_id for hit in result.vector] == ["a", "c"]
        assert all(hit.memory_ref == HEAD for hit in (*result.fts, *result.vector))
        assert result.fts[0].text == "exact b"
        assert result.vector[0].distance == 0.25
        index.vector.vector_complete.assert_awaited_once_with(connection, "scope-a", (HEAD,), PROFILE)

    asyncio.run(scenario())


@pytest.mark.parametrize("changes", [{"query_vector": None}, {"embedding_profile": None}])
def test_hybrid_refuses_incompatible_embedding_before_candidate_query(changes):
    async def scenario():
        connection = MagicMock(spec=AsyncConnection)
        connection.execute = AsyncMock()
        with pytest.raises(CapabilityNotSupportedError):
            await SeekDBMemoryIndex(PROFILE).search(connection, "scope-a", _request(**changes))
        connection.execute.assert_not_awaited()

    asyncio.run(scenario())


def test_hybrid_keeps_vector_completeness_gate():
    async def scenario():
        index = SeekDBMemoryIndex(PROFILE)
        index.vector.vector_complete = AsyncMock(return_value=False)
        connection = MagicMock(spec=AsyncConnection)
        connection.execute = AsyncMock()
        with pytest.raises(CapabilityNotSupportedError):
            await index.search(connection, "scope-a", _request())
        connection.execute.assert_not_awaited()

    asyncio.run(scenario())


def test_hybrid_propagates_stale_head_without_candidate_query():
    async def scenario():
        index = SeekDBMemoryIndex(PROFILE)
        index.vector.vector_complete = AsyncMock(side_effect=CapabilityNotSupportedError("head"))
        connection = MagicMock(spec=AsyncConnection)
        connection.execute = AsyncMock()
        with pytest.raises(CapabilityNotSupportedError, match="head"):
            await index.search(connection, "scope-a", _request())
        connection.execute.assert_not_awaited()

    asyncio.run(scenario())


def test_analyzed_query_is_bound_not_interpolated():
    async def scenario():
        index = SeekDBMemoryIndex(PROFILE)
        index.vector.vector_complete = AsyncMock(return_value=True)
        connection = MagicMock(spec=AsyncConnection)
        connection.execute = AsyncMock(return_value=MagicMock())
        connection.execute.return_value.mappings.return_value.all.return_value = []
        query = "alpha ' OR 1=1; --"
        result = await index.search(connection, "scope-a", _request(analyzed_query=query))
        statement, parameters = connection.execute.call_args.args
        assert query not in str(statement)
        assert parameters["query"] == query
        assert result.fts == result.vector == ()

    asyncio.run(scenario())


@pytest.mark.parametrize("mode, strategy", [("fts", "fts"), ("vector", "vector")])
def test_single_channels_delegate_to_existing_strategies(mode, strategy):
    async def scenario():
        index = SeekDBMemoryIndex(PROFILE)
        target = getattr(index, strategy)
        target.search = AsyncMock()
        request = _request(mode=mode)
        connection = MagicMock(spec=AsyncConnection)
        result = await index.search(connection, "scope-a", request)
        target.search.assert_awaited_once_with(connection, "scope-a", request)
        assert result is target.search.return_value

    asyncio.run(scenario())


@pytest.mark.skipif(importlib.util.find_spec("pylibseekdb") is None, reason="requires real embedded pylibseekdb")
def test_live_seekdb_candidates_match_double_query_baseline_and_use_both_indexes(tmp_path):
    from powercontext.builtin.artifacts.memory import MemoryEntryInput
    from powercontext.builtin.inference import EmbeddingResult
    from powercontext.builtin.persistence.memory_index import CompositeMemoryIndex
    from powercontext.builtin.persistence.oceanbase.memory_index import (
        OceanBaseMemoryFTSIndex,
        OceanBaseMemoryVectorIndex,
    )
    from powercontext.builtin.persistence.seekdb import SeekDBConfig
    from powercontext.builtin.runtime import BuiltinConfig, open_builtin_contexts

    class Embedding:
        profile = PROFILE

        async def embed(self, texts, /):
            return EmbeddingResult(
                vectors=tuple((1.0, 0.0, 0.0) if "alpha" in t.lower() else (0.0, 1.0, 0.0) for t in texts)
            )

    async def scenario():
        statements = []

        def record(_connection, _cursor, statement, parameters, _context, _executemany):
            if "AGAINST" in statement.upper() or "l2_distance" in statement.lower():
                statements.append((statement, parameters))

        async with open_builtin_contexts(
            BuiltinConfig(database=SeekDBConfig(path=tmp_path / "db")), embedding_model=Embedding()
        ) as contexts:
            memory = (await contexts.get("project")).artifacts.memory
            first = await memory.remember(
                memory=None, entries=(MemoryEntryInput(kind="fact", text="Alpha exact text."),), mode="append"
            )
            head = await memory.remember(
                memory=first, entries=(MemoryEntryInput(kind="fact", text="Beta second text."),), mode="append"
            )
            assert head is not None
            request = _request(memories=(head.as_ref(),))
            baseline = CompositeMemoryIndex(OceanBaseMemoryFTSIndex(), OceanBaseMemoryVectorIndex(PROFILE))
            current = SeekDBMemoryIndex(PROFILE)
            event.listen(Engine, "before_cursor_execute", record)
            try:
                async with contexts.database.transaction() as connection:
                    old = await baseline.search(connection, "project", request)
                    old_sql = statements[:]
                    statements.clear()
                    new = await current.search(connection, "project", request)
                    new_sql = statements[:]
                    statements.clear()
                    assert len(old_sql) == 2
                    assert len(new_sql) == 1
                    assert old == new
                    plan = "\n".join(
                        str(row[0])
                        for row in (await connection.exec_driver_sql("EXPLAIN " + new_sql[0][0], new_sql[0][1])).all()
                    )
                    assert "TEXT RETRIEVAL SCAN" in plan and "VECTOR INDEX" in plan
                result = await memory.search("alpha", memories=(head,), mode="hybrid", limit=10)
                assert result.hits[0].text == "Alpha exact text."
                assert result.hits[0].memory_ref == head.as_ref()
                assert result.hits[0].matched_by == ("fts", "vector")
                repeated = await memory.search("alpha", memories=(head,), mode="hybrid", limit=10)
                assert result.hits == repeated.hits
                (tmp_path / "native-evidence.json").write_text(
                    json.dumps(
                        {
                            "baseline": old.model_dump(mode="json"),
                            "candidate": new.model_dump(mode="json"),
                            "explain": plan,
                            "old_sql": old_sql,
                            "new_sql": new_sql,
                        },
                        default=str,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            finally:
                event.remove(Engine, "before_cursor_execute", record)

    asyncio.run(scenario())


@pytest.mark.skipif(importlib.util.find_spec("pylibseekdb") is None, reason="requires real embedded pylibseekdb")
def test_live_tagged_hybrid_uses_vector_index_without_losing_filtered_candidates(tmp_path):
    import math

    from powercontext.builtin.artifacts.memory import MemoryEntryInput
    from powercontext.builtin.inference import EmbeddingResult
    from powercontext.builtin.persistence.memory_index import CompositeMemoryIndex
    from powercontext.builtin.persistence.oceanbase.memory_index import (
        OceanBaseMemoryFTSIndex,
        OceanBaseMemoryVectorIndex,
    )
    from powercontext.builtin.persistence.seekdb import SeekDBConfig
    from powercontext.builtin.runtime import BuiltinConfig, open_builtin_contexts
    from powercontext.builtin.tags import MemoryEntryTagTarget

    class Embedding:
        profile = PROFILE

        async def embed(self, texts, /):
            vectors = []
            for value in texts:
                number = int(value.rsplit(" ", 1)[1]) if value.startswith("Alpha record ") else 0
                angle = number / 100
                vectors.append((math.cos(angle), math.sin(angle), 0.0))
            return EmbeddingResult(vectors=tuple(vectors))

    async def scenario():
        statements = []

        def record(_connection, _cursor, statement, parameters, _context, _executemany):
            if "AGAINST" in statement.upper() or "l2_distance" in statement.lower():
                statements.append((statement, parameters))

        async with open_builtin_contexts(
            BuiltinConfig(database=SeekDBConfig(path=tmp_path / "db")), embedding_model=Embedding()
        ) as contexts:
            memory = (await contexts.get("project")).artifacts.memory
            head = await memory.remember(
                memory=None,
                entries=tuple(MemoryEntryInput(kind="fact", text=f"Alpha record {i}") for i in range(80)),
                mode="append",
            )
            assert head is not None
            for entry in await memory.entries(head):
                number = int(entry.text.rsplit(" ", 1)[1])
                tags = tuple(
                    tag
                    for tag, selected in (("few", number >= 77), ("many", number >= 48), ("even", number % 2 == 0))
                    if selected
                )
                if tags:
                    target = MemoryEntryTagTarget(artifact_id=head.artifact_id, entry_id=entry.entry_id)
                    previous = await contexts.records.get_tags("project", target)
                    await contexts.records.replace_tags("project", target, tags, expected_etag=previous.etag)
            baseline = CompositeMemoryIndex(OceanBaseMemoryFTSIndex(), OceanBaseMemoryVectorIndex(PROFILE))
            current = SeekDBMemoryIndex(PROFILE)
            for tag_filter in (
                TagFilter(tags=("few",)),
                TagFilter(tags=("many", "even")),
                TagFilter(tags=("few", "even"), match="any"),
                TagFilter(tags=("absent",)),
            ):
                request = _request(memories=(head.as_ref(),), tag_filter=tag_filter)
                async with contexts.database.transaction() as connection:
                    old = await baseline.search(connection, "project", request)
                    statements.clear()
                    event.listen(Engine, "before_cursor_execute", record)
                    try:
                        new = await current.search(connection, "project", request)
                    finally:
                        event.remove(Engine, "before_cursor_execute", record)
                    assert len(statements) == 1
                    assert old == new
                    sql, parameters = statements[0]
                    # JSON preserves the full plan when native text EXPLAIN packet reads fail.
                    plan = "\n".join(
                        str(row[0])
                        for row in (await connection.exec_driver_sql("EXPLAIN FORMAT=JSON " + sql, parameters)).all()
                    )
                    assert "TEXT RETRIEVAL SCAN" in plan
                    assert "VECTOR INDEX" in plan

    asyncio.run(scenario())
