"""HTTP scoring adapter preserving global Memory candidate ranks."""

from __future__ import annotations

import math

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage


class HTTPMemoryReranker:
    """Score bounded batches with a caller-owned client, then select globally."""

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = "http-cross-encoder-v1",
    ) -> None:
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")  # noqa: TRY003
        self._endpoint = endpoint
        self._client = client
        self._batch_size = batch_size
        self.policy_id = policy_id

    async def rerank(self, query: str, candidates: tuple[MemoryHit, ...], limit: int, /) -> MemoryRerankDecision:
        """Return original ranks ordered by descending score and ascending rank."""
        if not candidates or type(limit) is not int or not 1 <= limit <= len(candidates):
            raise ValueError("nonempty candidates and an integer limit within their bounds are required")  # noqa: TRY003
        scores: dict[int, int | float] = {}
        requests = 0
        for start in range(0, len(candidates), self._batch_size):
            batch = [
                {"rank": rank, "text": hit.text}
                for rank, hit in enumerate(candidates[start : start + self._batch_size], start=start + 1)
            ]
            response = await self._client.post(self._endpoint, json={"query": query, "candidates": batch})
            requests += 1
            response.raise_for_status()
            scores.update(_batch_scores(response.json(), set(range(start + 1, start + len(batch) + 1))))
        return MemoryRerankDecision(
            selected_ranks=tuple(sorted(scores, key=lambda rank: (-scores[rank], rank))[:limit]),
            usage=InferenceUsage(requests=requests),
        )


def _batch_scores(payload: object, expected: set[int]) -> dict[int, int | float]:
    if not isinstance(payload, dict) or set(payload) != {"scores"} or not isinstance(payload["scores"], list):
        raise ValueError("response must contain exactly a scores list")  # noqa: TRY003
    scores: dict[int, int | float] = {}
    for item in payload["scores"]:
        if not isinstance(item, dict) or set(item) != {"rank", "score"}:
            raise ValueError("score records must contain exactly rank and score")  # noqa: TRY003
        rank, score = item["rank"], item["score"]
        if type(rank) is not int or rank not in expected or rank in scores:
            raise ValueError("ranks must cover the current batch exactly once")  # noqa: TRY003
        if type(score) not in (int, float) or (isinstance(score, float) and not math.isfinite(score)):
            raise ValueError("score must be a finite number")  # noqa: TRY003
        scores[rank] = score
    if scores.keys() != expected:
        raise ValueError("response is missing batch ranks")  # noqa: TRY003
    return scores
