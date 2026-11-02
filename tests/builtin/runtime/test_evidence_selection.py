from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import MemoryEntryInput, MemoryHit
from powercontext.builtin.runtime import (
    BuiltinConfig,
    ContextAssembly,
    PrepareContextRequest,
    RememberMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.context_pack import ContextPack
from powercontext.builtin.runtime.errors import PreparedContextInvariantError
from powercontext.builtin.runtime.prepared_context import PreparedContextBuilder, PreparedMemoryCandidates
from powercontext.builtin.runtime.prepared_text import TRUST_POLICY
from powercontext.builtin.scope import ScopeDraft

REF = ArtifactRef(family="memory", artifact_id="memory", revision=9)


def group(scope: str, texts: tuple[str, ...], *, long_ids: bool = False) -> PreparedMemoryCandidates:
    return PreparedMemoryCandidates(
        scope_id=scope,
        memory_ref=REF,
        hits=tuple(
            MemoryHit(
                memory_ref=REF,
                entry_id=f"entry-{index}" + ("x" * 220 if long_ids else ""),
                entry_version_id=f"version-{index}",
                text=text,
                score=1.0,
                matched_by=("fts",),
            )
            for index, text in enumerate(texts)
        ),
    )


def check(build, groups, budget):
    content = build.context.content or ""
    assert build.context.content_bytes == len(content.encode("utf-8")) <= budget
    assert len(build.origins) == len(build.fragments)
    if not content:
        assert not build.fragments
        return []
    assert content.startswith(TRUST_POLICY + "\n\nBEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1\n")
    assert content.endswith("\nEND_POWERCONTEXT_PREPARED_CONTEXT_V1")
    payload = json.loads(content.splitlines()[-2])
    assert payload["trust"] == "untrusted_history"
    assert len(payload["items"]) == len(build.fragments)
    originals = {(g.scope_id, h.entry_id, h.entry_version_id): h for g in groups for h in g.hits}
    for item, fragment, origin in zip(payload["items"], build.fragments, build.origins, strict=True):
        address = fragment.address
        assert origin == address
        hit = originals[(address.memory.scope_id, address.entry_id, address.entry_version_id)]
        assert address.memory.artifact == hit.memory_ref
        assert type(fragment.start) is int and type(fragment.end) is int
        assert 0 <= fragment.start < fragment.end <= len(hit.text)
        assert fragment.text == hit.text[fragment.start : fragment.end]
        assert item == {
            "citation": {
                "scope_id": address.memory.scope_id,
                "memory_ref": hit.memory_ref.model_dump(mode="json"),
                "entry_id": hit.entry_id,
                "entry_version_id": hit.entry_version_id,
            },
            "content": fragment.text,
            "start": fragment.start,
            "end": fragment.end,
        }
    return payload["items"]


def test_strict_opt_in_default_preserves_original_prepare():
    assert PrepareContextRequest(query="test").evidence_selection is False
    for value in (0, 1, "true", None):
        with pytest.raises(ValidationError):
            PrepareContextRequest.model_validate({"query": "test", "evidence_selection": value})
    builder = PreparedContextBuilder()
    groups = (group("s", ("Original unmodified evidence.",)),)
    old = builder.build_scopes_result(
        request=PrepareContextRequest(query="evidence"), current_scope_id="s", memory_candidates=groups
    )
    explicit = builder.build_scopes_result(
        request=PrepareContextRequest(query="evidence", evidence_selection=False),
        current_scope_id="s",
        memory_candidates=groups,
    )
    assert old == explicit
    assert old.fragments == ()
    assert old.context.content is not None
    assert json.loads(old.context.content.splitlines()[-2])["items"][0]["truncated"] is False


@pytest.mark.parametrize("budget", [512, 600, 799, 1000, 1200, 1400, 1800])
@pytest.mark.parametrize("long_ids", [False, True])
def test_literal_coordinates_unicode_escaping_and_exact_budget(budget, long_ids):
    text = '背景说明。海洋 station says "温度\\稳定".\nEvidence reports 37.5 degrees, not 19 degrees. ' * 8
    groups = (group("scope-unicode", (text,), long_ids=long_ids),)
    request = PrepareContextRequest(query="海洋 station 37.5 degrees", evidence_selection=True, max_bytes=budget)
    result = PreparedContextBuilder().build_scopes_result(
        request=request, current_scope_id="scope-unicode", memory_candidates=groups
    )
    check(result, groups, budget)


def test_query_changes_late_evidence_and_preserves_same_text_scope_identity():
    prefix = "Unrelated administrative background. " * 80
    text = prefix + "Cobalt sensors measure the response at 37 degrees. " + prefix + "Amber valves close at 19 degrees."
    groups = (group("first", (text,)), group("second", (text,)))
    builder = PreparedContextBuilder()
    selections = []
    for query in ("cobalt sensors response", "amber valves close"):
        result = builder.build_scopes_result(
            request=PrepareContextRequest(query=query, max_bytes=1800, evidence_selection=True),
            current_scope_id="first",
            memory_candidates=groups,
        )
        check(result, groups, 1800)
        assert result.fragments
        selections.append(" ".join(f.text for f in result.fragments))
        assert any(f.end > len(prefix) for f in result.fragments)
    assert "Cobalt" in selections[0]
    assert "Amber" in selections[1]
    assert selections[0] != selections[1]


def test_multiple_documents_compete_and_probe_matches_builder():
    groups = (
        group(
            "s",
            (
                "Cobalt observations confirm a decline of 37 percent.",
                "Cobalt measurements independently confirm a decline of 19 percent.",
            ),
        ),
    )
    builder = PreparedContextBuilder()
    request = PrepareContextRequest(
        query="cobalt decline observations measurements",
        max_bytes=1800,
        evidence_selection=True,
        include_code=True,
        assembly=ContextAssembly(sections=()),
    )
    result = builder.build_scopes_result(request=request, current_scope_id="s", memory_candidates=groups)
    check(result, groups, 1800)
    assert len(result.fragments) >= 2
    probe = builder.probe_budget(request=request, current_scope_id="s", memory_candidates=groups)
    assert probe.delivered_items == len(result.fragments)
    assert probe.unused_bytes == request.max_bytes - result.context.content_bytes


def test_empty_budget_and_empty_candidates_have_no_invented_evidence():
    builder = PreparedContextBuilder()
    request = PrepareContextRequest(query="evidence", max_bytes=512, evidence_selection=True)
    for groups in ((), (group("s", ("Evidence text.",), long_ids=True),)):
        result = builder.build_scopes_result(request=request, current_scope_id="s", memory_candidates=groups)
        check(result, groups, 512)
        assert result.context.content is None


def test_one_entry_can_supply_two_distant_nonoverlapping_fragments():
    text = "Cobalt sensors measure 37 degrees. " + "Unrelated bookkeeping. " * 100 + "Amber valves measure 19 degrees."
    groups = (group("s", (text,)),)
    result = PreparedContextBuilder().build_scopes_result(
        request=PrepareContextRequest(query="cobalt sensors amber valves", evidence_selection=True, max_bytes=1800),
        current_scope_id="s",
        memory_candidates=groups,
    )
    check(result, groups, 1800)
    assert len(result.fragments) >= 2
    assert "Cobalt" in result.fragments[0].text and "Amber" in result.fragments[-1].text
    assert all(left.end < right.start for left, right in zip(result.fragments, result.fragments[1:], strict=False))


def test_scope_is_required_for_selection_but_no_scope_is_invented():
    with pytest.raises(PreparedContextInvariantError, match="evidence-scope-missing"):
        PreparedContextBuilder().build_scopes_result(
            request=PrepareContextRequest(query="evidence", evidence_selection=True),
            current_scope_id=None,
            memory_candidates=(group("", ("Evidence statement.",)),),
        )


def test_budget_floor_reports_omissions_to_existing_recall_gate():
    groups = (group("s", ("Evidence text.",), long_ids=True),)
    request = PrepareContextRequest(query="evidence", evidence_selection=True, max_bytes=512)
    builder = PreparedContextBuilder()
    result = builder.build_scopes_result(request=request, current_scope_id="s", memory_candidates=groups)
    assert result.context.status == "empty"
    assert result.omissions.dropped_items == 1
    assert result.omissions.dropped_no_fitting_truncation == 1
    probe = builder.probe_budget(request=request, current_scope_id="s", memory_candidates=groups)
    assert probe.delivered_items == 0 and probe.dropped_items == 1
    assert probe.budget_bounded is True


def test_final_serialized_size_is_the_boundary_including_escaping():
    groups = (group("s", ('A cobalt sensor reports "37" degrees with \\ precision.\nResults confirm it.',)),)
    builder = PreparedContextBuilder()
    large = builder.build_scopes_result(
        request=PrepareContextRequest(query="cobalt sensor", evidence_selection=True, max_bytes=1800),
        current_scope_id="s",
        memory_candidates=groups,
    )
    exact = large.context.content_bytes
    assert exact >= 512
    for budget in (exact - 1, exact, exact + 1):
        result = builder.build_scopes_result(
            request=PrepareContextRequest(query="cobalt sensor", evidence_selection=True, max_bytes=budget),
            current_scope_id="s",
            memory_candidates=groups,
        )
        check(result, groups, budget)
        if budget >= exact:
            assert result.context.content == large.context.content


def test_runtime_and_incremental_share_exact_evidence_body():
    async def run():
        async with open_builtin_runtime(BuiltinConfig()) as runtime:
            assert runtime.scopes is not None
            scope = await runtime.scopes.create(
                ScopeDraft(title="selection", summary="offline literal", idempotency_key="selection")
            )
            await runtime.memory.for_scope(scope.scope_id).remember(
                RememberMemoryRequest(
                    entries=(
                        MemoryEntryInput(kind="fact", text="Background. " * 70 + "Cobalt sensors report 37 degrees."),
                    )
                )
            )
            service = runtime.context.for_scope(scope.scope_id)
            request = PrepareContextRequest(query="cobalt sensors", evidence_selection=True, max_bytes=1400)
            prepared = await service.prepare(request)
            assert prepared.content and "Cobalt" in prepared.content
            pack = await service.prepare_incremental(request)
            assert isinstance(pack, ContextPack)
            assert b"".join(pack.items).decode("utf-8") == prepared.content

    asyncio.run(run())
