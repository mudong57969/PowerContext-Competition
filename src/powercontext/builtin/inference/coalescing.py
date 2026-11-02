# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0

"""Event-loop-local embedding request sharing and successful-vector LRU caching."""

from __future__ import annotations

import asyncio
import math
from collections import OrderedDict
from dataclasses import dataclass

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage
from powercontext.builtin.inference.protocols import EmbeddingModel


# Use object identity so distinct provider batches count separately even with equal usage values.
@dataclass(frozen=True, eq=False)
class _BatchUsage:
    usage: InferenceUsage


_VectorResult = tuple[EmbeddingVector, _BatchUsage]


def _observe_failure(future: asyncio.Future[_VectorResult]) -> None:
    # Work may outlive every caller; retrieve errors even when nobody remains to await it.
    if not future.cancelled():
        future.exception()


class CoalescingEmbeddingModel:
    """Share pending/in-flight texts and cache successful vectors within one event loop.

    Each caller receives the provider usage of every distinct batch it waits for.
    Cancelling a caller leaves shared provider work running, including cache population.
    """

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        if type(max_batch_size) is not int or max_batch_size <= 0:
            message = "max_batch_size must be a positive integer"
            raise ValueError(message)
        if type(cache_size) is not int or cache_size < 0:
            message = "cache_size must be a nonnegative integer"
            raise ValueError(message)
        if (
            isinstance(coalesce_ms, bool)
            or not isinstance(coalesce_ms, (int, float))
            or not math.isfinite(coalesce_ms)
            or coalesce_ms < 0
        ):
            message = "coalesce_ms must be finite and nonnegative"
            raise ValueError(message)
        self.profile = model.profile
        self._model = model
        self._max_batch_size = max_batch_size
        self._coalesce_seconds = coalesce_ms / 1000
        self._cache_size = cache_size
        self._cache: OrderedDict[str, EmbeddingVector] = OrderedDict()
        self._inflight: dict[str, asyncio.Future[_VectorResult]] = {}
        self._pending: dict[str, asyncio.Future[_VectorResult]] = {}
        self._dispatch_handle: asyncio.TimerHandle | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        """Return vectors in input order, preserving duplicates and per-call batch usage."""
        vectors: dict[str, EmbeddingVector] = {}
        waiting: dict[str, asyncio.Future[_VectorResult]] = {}
        loop = asyncio.get_running_loop()
        for text in texts:
            if text in self._cache:
                vectors[text] = self._cache[text]
                self._cache.move_to_end(text)
                continue
            future = self._inflight.get(text)
            if future is None:
                future = loop.create_future()
                future.add_done_callback(_observe_failure)
                self._inflight[text] = future
                self._pending[text] = future
            waiting[text] = future
        if self._pending and self._dispatch_handle is None:
            self._dispatch_handle = loop.call_later(self._coalesce_seconds, self._dispatch)

        results = await asyncio.gather(*(asyncio.shield(future) for future in waiting.values()))
        batches: set[_BatchUsage] = set()
        for text, (vector, batch) in zip(waiting, results, strict=True):
            vectors[text] = vector
            batches.add(batch)
        usages = [batch.usage for batch in batches]
        usage = InferenceUsage(
            requests=sum(item.requests for item in usages),
            input_tokens=self._sum_tokens([item.input_tokens for item in usages]),
            output_tokens=self._sum_tokens([item.output_tokens for item in usages]),
        )
        return EmbeddingResult(vectors=tuple(vectors[text] for text in texts), usage=usage)

    @staticmethod
    def _sum_tokens(values: list[int | None]) -> int | None:
        return (
            None
            if not values or any(value is None for value in values)
            else sum(value for value in values if value is not None)
        )

    def _dispatch(self) -> None:
        self._dispatch_handle = None
        pending = list(self._pending.items())
        self._pending.clear()
        for start in range(0, len(pending), self._max_batch_size):
            task = asyncio.create_task(self._run_batch(pending[start : start + self._max_batch_size]))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _run_batch(self, entries: list[tuple[str, asyncio.Future[_VectorResult]]]) -> None:
        try:
            result = await self._model.embed(tuple(text for text, _ in entries))
            if len(result.vectors) != len(entries):
                message = "provider vector count does not match batch text count"
                raise ValueError(message)  # noqa: TRY301 - fail all waiters of this batch together
            batch = _BatchUsage(result.usage)
            for (text, future), vector in zip(entries, result.vectors, strict=True):
                if self._cache_size:
                    self._cache[text] = vector
                    self._cache.move_to_end(text)
                    while len(self._cache) > self._cache_size:
                        self._cache.popitem(last=False)
                future.set_result((vector, batch))
        except asyncio.CancelledError:
            for _, future in entries:
                future.cancel()
            raise
        except Exception as error:
            for _, future in entries:
                future.set_exception(error)
        finally:
            for text, _ in entries:
                del self._inflight[text]


__all__ = ["CoalescingEmbeddingModel"]
