from __future__ import annotations

import asyncio
from typing import Any

import pytest

from powercontext.builtin.artifacts.memory import EmbeddingProfile
from powercontext.builtin.inference import EmbeddingResult, InferenceUsage
from powercontext.builtin.inference.coalescing import CoalescingEmbeddingModel


class Provider:
    profile = EmbeddingProfile(profile_id="coalescing-test", model="offline", dimension=1)

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.usage = InferenceUsage(requests=3, input_tokens=7, output_tokens=0)

    async def embed(self, texts: tuple[str, ...]) -> EmbeddingResult:
        self.calls.append(texts)
        self.started.set()
        await self.release.wait()
        if "fail" in texts:
            message = "provider failure"
            raise RuntimeError(message)
        return EmbeddingResult(vectors=tuple((float(len(text)),) for text in texts), usage=self.usage)


def test_late_waiter_without_cache_and_distinct_batch_usage() -> None:
    async def run() -> None:
        base = Provider()
        model = CoalescingEmbeddingModel(base, max_batch_size=1, coalesce_ms=0, cache_size=0)
        assert model.profile is base.profile
        first = asyncio.create_task(model.embed(("one", "four", "one")))
        await base.started.wait()
        late = asyncio.create_task(model.embed(("four", "one")))
        await asyncio.sleep(0)
        base.release.set()
        for result in await asyncio.gather(first, late):
            assert result.usage == InferenceUsage(requests=6, input_tokens=14, output_tokens=0)
        assert (await first).vectors == ((3.0,), (4.0,), (3.0,))
        assert base.calls == [("one",), ("four",)]
        await model.embed(("one",))
        assert base.calls[-1] == ("one",)
        assert len(base.calls) == 3

    asyncio.run(asyncio.wait_for(run(), 5))


def test_equal_usage_values_do_not_merge_distinct_batches() -> None:
    async def run() -> None:
        base = Provider()
        base.usage = InferenceUsage(requests=1, input_tokens=5)
        base.release.set()
        model = CoalescingEmbeddingModel(base, max_batch_size=1, coalesce_ms=0)
        result = await model.embed(("first", "second", "third"))
        assert len(base.calls) == 3
        assert result.usage.requests == 3
        assert result.usage.input_tokens == 15

    asyncio.run(asyncio.wait_for(run(), 5))


def test_failed_batch_does_not_cancel_independent_work() -> None:
    async def run() -> None:
        base = Provider()
        model = CoalescingEmbeddingModel(base, max_batch_size=1, coalesce_ms=0)
        mixed = asyncio.create_task(model.embed(("fail", "good")))
        await base.started.wait()
        good = asyncio.create_task(model.embed(("good",)))
        await asyncio.sleep(0)
        base.release.set()
        with pytest.raises(RuntimeError, match="provider failure"):
            await mixed
        assert (await good).vectors == ((4.0,),)
        assert (await model.embed(("good",))).usage.requests == 0
        with pytest.raises(RuntimeError):
            await model.embed(("fail",))
        assert base.calls.count(("fail",)) == 2

    asyncio.run(asyncio.wait_for(run(), 5))


def test_all_waiters_cancelled_work_still_populates_cache() -> None:
    async def run() -> None:
        base = Provider()
        model = CoalescingEmbeddingModel(base, coalesce_ms=0)
        first = asyncio.create_task(model.embed(("shared",)))
        await base.started.wait()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        survivor = asyncio.create_task(model.embed(("shared",)))
        base.release.set()
        assert (await survivor).vectors == ((6.0,),)
        assert (await model.embed(("shared",))).usage.requests == 0
        assert base.calls == [("shared",)]

    asyncio.run(asyncio.wait_for(run(), 5))


def test_cache_duplicate_access_refreshes_lru_in_input_order() -> None:
    async def run() -> None:
        base = Provider()
        base.release.set()
        model = CoalescingEmbeddingModel(base, coalesce_ms=0, cache_size=2)
        await model.embed(("a", "b"))
        await model.embed(("a", "b", "a"))
        await model.embed(("c",))
        assert (await model.embed(("a",))).usage.requests == 0
        await model.embed(("b",))
        assert sum(call.count("b") for call in base.calls) == 2

    asyncio.run(asyncio.wait_for(run(), 5))


def test_unknown_token_usage_stays_unknown_across_batches() -> None:
    class MixedUsage(Provider):
        async def embed(self, texts: tuple[str, ...]) -> EmbeddingResult:
            return EmbeddingResult(
                vectors=((1.0,),),
                usage=InferenceUsage(requests=2, input_tokens=7 if texts == ("known",) else None, output_tokens=0),
            )

    async def run() -> None:
        model = CoalescingEmbeddingModel(MixedUsage(), max_batch_size=1, coalesce_ms=0)
        result = await model.embed(("known", "unknown"))
        assert result.usage == InferenceUsage(requests=4, input_tokens=None, output_tokens=0)

    asyncio.run(asyncio.wait_for(run(), 5))


@pytest.mark.parametrize("count", [0, 2])
def test_invalid_vector_count_can_retry(count: int) -> None:
    class WrongCount(Provider):
        async def embed(self, texts: tuple[str, ...]) -> EmbeddingResult:
            self.calls.append(texts)
            size = count if len(self.calls) == 1 else len(texts)
            return EmbeddingResult(vectors=tuple((1.0,) for _ in range(size)))

    async def run() -> None:
        base = WrongCount()
        model = CoalescingEmbeddingModel(base, coalesce_ms=0)
        with pytest.raises(ValueError):
            await model.embed(("retry",))
        assert (await model.embed(("retry",))).vectors == ((1.0,),)
        assert len(base.calls) == 2

    asyncio.run(asyncio.wait_for(run(), 5))


def test_cancel_before_dispatch_and_unobserved_failure_are_isolated() -> None:
    async def run() -> None:
        errors: list[dict[str, object]] = []
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda _, context: errors.append(context))
        base = Provider()
        model = CoalescingEmbeddingModel(base, coalesce_ms=10)
        abandoned = asyncio.create_task(model.embed(("fail",)))
        await asyncio.sleep(0)
        abandoned.cancel()
        with pytest.raises(asyncio.CancelledError):
            await abandoned
        await base.started.wait()
        base.release.set()
        # A separate call is an observable completion barrier for the abandoned batch.
        assert (await model.embed(("good",))).vectors == ((4.0,),)
        await asyncio.sleep(0)
        assert not errors
        with pytest.raises(RuntimeError):
            await model.embed(("fail",))
        assert base.calls.count(("fail",)) == 2

    asyncio.run(asyncio.wait_for(run(), 5))


@pytest.mark.parametrize("cache_size", [0, 64])
@pytest.mark.parametrize("coalesce_ms", [0, 5])
def test_many_callers_share_all_unique_texts(cache_size: int, coalesce_ms: float) -> None:
    async def run() -> None:
        base = Provider()
        base.release.set()
        model = CoalescingEmbeddingModel(base, max_batch_size=7, coalesce_ms=coalesce_ms, cache_size=cache_size)
        texts = tuple(f"中文😀 {index}" for index in range(31))
        results = await asyncio.gather(*(model.embed(texts + texts[:3]) for _ in range(100)))
        assert len(base.calls) == 5
        assert tuple(text for batch in base.calls for text in batch) == texts
        for result in results:
            assert result.vectors == tuple((float(len(text)),) for text in texts + texts[:3])
            assert result.usage == InferenceUsage(requests=15, input_tokens=35, output_tokens=0)

    asyncio.run(asyncio.wait_for(run(), 5))


@pytest.mark.parametrize(
    "options",
    [
        {"max_batch_size": 0},
        {"max_batch_size": True},
        {"cache_size": -1},
        {"cache_size": 1.5},
        {"coalesce_ms": -1},
        {"coalesce_ms": float("nan")},
        {"coalesce_ms": float("inf")},
    ],
)
def test_invalid_configuration(options: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        CoalescingEmbeddingModel(Provider(), **options)
