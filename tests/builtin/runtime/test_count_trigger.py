"""Count admission uses persistent journal identities, not sequence arithmetic."""

import asyncio

import pytest
from sqlalchemy import insert

from powercontext.builtin.persistence.cursors import SourceCursorRepository
from powercontext.builtin.persistence.processing_intents import ArtifactProcessingIntentRepository
from powercontext.builtin.persistence.tables import SOURCES_TABLE
from powercontext.builtin.runtime.artifact_processing import ArtifactProcessingBinding, ArtifactProcessingSupervisor
from powercontext.builtin.runtime.processing_discovery import source_count_scopes
from powercontext.builtin.sources import SourceCursor
from tests.builtin.runtime.test_processing_scheduler import _intent, _Launcher, _profile, _request, _wait


@pytest.mark.asyncio
@pytest.mark.parametrize("threshold", [1, 2, 3, 5])
async def test_count_uses_rows_after_each_family_cursor_even_with_sequence_gaps(tmp_path, threshold):
    async with (
        _profile(tmp_path, "count-gaps") as profile,
        profile.database.transaction() as connection,
    ):
        for scope in ("left", "right"):
            for position in (2, 11, 90):
                await connection.execute(
                    insert(SOURCES_TABLE).values(
                        scope_id=scope,
                        source_type="content",
                        source_id=str(position),
                        payload=b"not-read-by-metadata-count",
                        journal_position=position,
                    )
                )
        await SourceCursorRepository().save(
            connection, "left", "memory-binding", SourceCursor(sequence=11), expected_generation=None
        )
        assert await source_count_scopes(connection, ("left", "right"), binding_name="memory-binding", threshold=2) == {
            "right"
        }
        assert await source_count_scopes(connection, ("left", "right"), binding_name="topic-binding", threshold=3) == {
            "left",
            "right",
        }
        assert await source_count_scopes(connection, (), binding_name="memory-binding", threshold=1) == set()
        expected = ({"left"} if threshold == 1 else set()) | ({"right"} if threshold <= 3 else set())
        assert (
            await source_count_scopes(connection, ("left", "right"), binding_name="memory-binding", threshold=threshold)
            == expected
        )


@pytest.mark.asyncio
async def test_count_admission_is_paged_and_keeps_accepted_work_independent(tmp_path, monkeypatch):
    from powercontext.builtin.runtime import artifact_processing as processing

    monkeypatch.setattr(processing, "_DISCOVERY_PAGE_SIZE", 2)
    async with _profile(tmp_path, "count-pages") as profile:
        scopes = ("below", "a", "b", "c", "explicit")
        for scope in scopes:
            await _request(profile.database, "memory-binding", scope, requested=scope == "explicit")

        async def eligible(connection, candidates):
            return frozenset(candidates) - {"below", "explicit"}

        launcher = _Launcher(profile.database)
        async with ArtifactProcessingSupervisor(
            database=profile.database,
            bindings=(ArtifactProcessingBinding("memory-binding", "memory", launcher, source_count_filter=eligible),),
            lease_mode="single-process",
        ):
            await _wait(lambda: len(launcher.assignments) == 4)
        assert {a.scope_id for a in launcher.assignments} == {"a", "b", "c", "explicit"}
        assert (await _intent(profile.database, "memory-binding", "below")).requested_generation == 0
        assert (await _intent(profile.database, "memory-binding", "explicit")).requested_generation == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["filter", "request"])
async def test_failed_count_page_does_not_skip_or_accept_partial_work(tmp_path, monkeypatch, boundary):
    from powercontext.builtin.runtime import artifact_processing as processing

    monkeypatch.setattr(processing, "_DISCOVERY_PAGE_SIZE", 2)

    class AdmissionFailure(Exception):
        pass

    class FailingIntents(ArtifactProcessingIntentRepository):
        fail = boundary == "request"

        async def request(self, connection, scope_id, binding_name, /):
            result = await super().request(connection, scope_id, binding_name)
            if self.fail and scope_id == "b":
                self.fail = False
                raise AdmissionFailure
            return result

    failed_filter = False

    async def eligible(connection, scopes):
        nonlocal failed_filter
        if boundary == "filter" and not failed_filter:
            failed_filter = True
            raise AdmissionFailure
        return frozenset(scopes)

    async with _profile(tmp_path, "count-rollback") as profile:
        for scope in ("a", "b", "c"):
            await _request(profile.database, "memory-binding", scope, requested=False)
        supervisor = ArtifactProcessingSupervisor(
            database=profile.database,
            bindings=(
                ArtifactProcessingBinding(
                    "memory-binding",
                    "memory",
                    _Launcher(profile.database),
                    source_count_filter=eligible,
                ),
            ),
            lease_mode="single-process",
            intents=FailingIntents(),
        )
        await supervisor._acquire()
        state = supervisor._families["memory-binding"]
        try:
            with pytest.raises(AdmissionFailure):
                await supervisor._discover_count(state)
            assert state.count_after == 0 and not state.ready
            for scope in ("a", "b", "c"):
                assert (await _intent(profile.database, "memory-binding", scope)).requested_generation == 0
            await supervisor._discover_count(state)
            assert set(state.ready) == {"a", "b"}
            await supervisor._dispatch(state)
            await asyncio.gather(*(worker.task for worker in state.running.values()))
            await supervisor._reap(state)
            await supervisor._discover_count(state)
            assert set(state.ready) == {"b", "c"}
            for scope in ("a", "b", "c"):
                assert (await _intent(profile.database, "memory-binding", scope)).requested_generation == 1
        finally:
            await supervisor.close()
