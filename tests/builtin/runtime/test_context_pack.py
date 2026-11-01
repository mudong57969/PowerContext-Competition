"""Transport boundary and independent reconstruction regressions."""

import json
from dataclasses import FrozenInstanceError

import pytest

from powercontext.builtin.runtime import (
    ContextPack,
    ContextPackDelta,
    ContextPackError,
    apply_context_pack_delta,
)


@pytest.mark.parametrize("content", ["", "中文🙂é\n下一行\r\n", "a" * 2000, "\n" * 40])
@pytest.mark.parametrize("limit", [4, 7, 512])
def test_utf8_bounds_and_determinism(content, limit):
    pack = ContextPack.from_content(content, chunk_bytes=limit)
    assert pack == ContextPack.from_content(content, chunk_bytes=limit)
    assert b"".join(pack.items).decode() == content
    assert all(len(item) <= limit and item.decode() for item in pack.items)
    assert ContextPack.from_bytes(pack.to_bytes()) == pack
    assert pack.byte_count == len(pack.to_bytes())


@pytest.mark.parametrize("limit", [True, False, 0, -1, 1.5, "512", None])
def test_invalid_chunk_limit(limit):
    with pytest.raises(ContextPackError):
        ContextPack.from_content("", chunk_bytes=limit)


@pytest.mark.parametrize("content,limit", [("🙂", 3), ("中", 2), ("é", 1), ("\ud800", 512), (None, 512)])
def test_unrepresentable_content(content, limit):
    with pytest.raises(ContextPackError):
        ContextPack.from_content(content, chunk_bytes=limit)


@pytest.mark.parametrize("size", [0, 1, 600, 630, 640, 7200, 7300, 7400])
def test_self_referential_byte_count_across_digit_boundaries(size):
    pack = ContextPack.build((b"a" * size,))
    wire = pack.to_bytes()
    assert json.loads(wire)["byte_count"] == len(wire) == pack.byte_count


def test_appending_lines_keeps_completed_chunks_reusable():
    content = "abc\n" * 90
    base = ContextPack.from_content(content)
    target = ContextPack.from_content(content + content)
    delta = ContextPackDelta.between(base, target)
    assert delta.prefix_items > 0
    assert apply_context_pack_delta(base, delta) == target


@pytest.mark.parametrize("decoder", [ContextPack, ContextPackDelta])
@pytest.mark.parametrize("raw", [b"", b"null", b"[]", b"{", b"\xff", b"{}", "{}", None])
def test_bad_wire_is_protocol_error(decoder, raw):
    with pytest.raises(ContextPackError):
        decoder.from_bytes(raw)


@pytest.mark.parametrize("encoded", ["?", "YQ", "YQ===", "YR==", "YQ==\n", "_w==", 7, None, "/w=="])
@pytest.mark.parametrize("is_delta", [False, True])
def test_noncanonical_base64_and_invalid_utf8(encoded, is_delta):
    pack = ContextPack.build((b"a",))
    message = ContextPackDelta.between(pack, pack) if is_delta else pack
    payload = json.loads(message.to_bytes())
    payload["appended" if is_delta else "items"] = [encoded]
    with pytest.raises(ContextPackError):
        type(message).from_bytes(json.dumps(payload).encode())


@pytest.mark.parametrize("is_delta", [False, True])
def test_exact_fields_types_and_duplicate_keys(is_delta):
    pack = ContextPack.build((b"a",))
    message = ContextPackDelta.between(pack, pack) if is_delta else pack
    payload = json.loads(message.to_bytes())
    mutations = [{**payload, "extra": 1}, {**payload, "schema": 1}]
    mutations += [{key: value for key, value in payload.items() if key != omitted} for omitted in payload]
    mutations += [{**payload, "appended" if is_delta else "items": "YQ=="}]
    if is_delta:
        mutations += [{**payload, "prefix_items": value} for value in (True, 0.0, -1, None)]
        mutations += [{**payload, "base_digest": value} for value in (None, 7, "sha256:abc")]
        mutations += [{**payload, "target_digest": value} for value in (None, [], "sha256:" + "A" * 64)]
    else:
        mutations += [{**payload, "byte_count": value} for value in (True, float(pack.byte_count), -1, None)]
        mutations += [{**payload, "digest": value} for value in (None, [], "sha256:" + "0" * 64)]
    for invalid in mutations:
        with pytest.raises(ContextPackError):
            type(message).from_bytes(json.dumps(invalid).encode())
    duplicate = message.to_bytes().replace(b"{", b'{"schema":"duplicate",', 1)
    with pytest.raises(ContextPackError):
        type(message).from_bytes(duplicate)


@pytest.mark.parametrize("target", ["new\nb\nc\n", "a\nnew\nc\n", "a\nb\nnew\n", "", "a\nb\nc\ntail"])
def test_independent_reconstruction_and_alternate_valid_prefix(target):
    base = ContextPack.from_content("a\nb\nc\n", chunk_bytes=2)
    target_pack = ContextPack.from_content(target, chunk_bytes=5)
    delta = ContextPackDelta.between(base, target_pack)
    rebuilt = apply_context_pack_delta(
        ContextPack.from_bytes(base.to_bytes()), ContextPackDelta.from_bytes(delta.to_bytes())
    )
    assert rebuilt == target_pack
    full_suffix = ContextPackDelta(base.digest, target_pack.digest, 0, target_pack.items)
    assert apply_context_pack_delta(base, full_suffix) == target_pack
    assert delta.byte_count == len(delta.to_bytes())


def test_bad_base_bounds_target_and_immutable_values():
    base = ContextPack.build((b"a",))
    for delta in (
        ContextPackDelta(base.digest, base.digest, 2, ()),
        ContextPackDelta(base.digest, "sha256:" + "0" * 64, 0, ()),
        ContextPackDelta("sha256:" + "0" * 64, base.digest, 1, ()),
    ):
        with pytest.raises(ContextPackError):
            apply_context_pack_delta(base, delta)
    with pytest.raises(FrozenInstanceError):
        base.items = ()  # ty: ignore[invalid-assignment]
    for invalid in ([b"a"], ("a",), (b"\xff",)):
        with pytest.raises(ContextPackError):
            ContextPack.build(invalid)  # ty: ignore[invalid-argument-type]


@pytest.mark.asyncio
async def test_runtime_empty_append_query_switch_and_citations():
    from powercontext.builtin.artifacts.memory import MemoryCandidateRequest, MemoryEntryInput
    from powercontext.builtin.runtime import BuiltinConfig, CaptureSource, PrepareContextRequest, open_builtin_runtime
    from powercontext.builtin.scope import ScopeDraft
    from powercontext.builtin.sources import ContentSource

    class Pipeline:
        async def extract(self, request: MemoryCandidateRequest, /) -> tuple[MemoryEntryInput, ...]:
            return tuple(
                MemoryEntryInput(kind="conversation-turn", text=source.content, sources=(source,))
                for source in request.sources
                if isinstance(source, ContentSource)
            )

    async with open_builtin_runtime(BuiltinConfig(), candidate_pipeline=Pipeline()) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(ScopeDraft(title="Pack", summary="test", idempotency_key="pack-test"))
        context = runtime.context.for_scope(scope.scope_id)
        request = PrepareContextRequest(query="remote")
        assert (await context.prepare(request)).content is None
        base = await context.prepare_incremental(request)
        assert isinstance(base, ContextPack) and base.items == ()
        for index, query in enumerate(("remote", "ocean", "absent")):
            await runtime.sources.for_scope(scope.scope_id).capture(
                CaptureSource(source_id=f"turn-{index}", content=f"{query} 中文🙂 discussion", metadata={})
            )
            while (await runtime.memory.for_scope(scope.scope_id).flush()).processed:
                pass
            request = PrepareContextRequest(query=query)
            before = await context.prepare(request)
            delta = await context.prepare_incremental(request, base_pack=base)
            after = await context.prepare(request)
            assert before == after
            assert isinstance(delta, ContextPackDelta)
            base = apply_context_pack_delta(
                ContextPack.from_bytes(base.to_bytes()), ContextPackDelta.from_bytes(delta.to_bytes())
            )
            assert b"".join(base.items).decode() == (after.content or "")
