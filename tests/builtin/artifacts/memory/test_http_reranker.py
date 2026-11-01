import asyncio
import json

import httpx
import pytest

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory.http_reranker import HTTPMemoryReranker
from powercontext.builtin.artifacts.memory.models import MemoryHit


def hits():
    return tuple(
        MemoryHit(
            memory_ref=ArtifactRef(family="memory", artifact_id="m", revision=1),
            entry_id=f"e{i}",
            entry_version_id=f"v{i}",
            text=f"text{i}",
            score=1.0,
            matched_by=("fts",),
        )
        for i in range(5)
    )


@pytest.mark.parametrize("batch_size", [1, 2, 7])
@pytest.mark.parametrize("limit", [1, 5])
def test_global_ties_identity_and_client_ownership(batch_size, limit):
    async def run():
        original = hits()
        snapshot = tuple(hit.model_dump() for hit in original)
        seen = []

        def handler(request):
            body = json.loads(request.content)
            assert set(body) == {"query", "candidates"}
            for item in body["candidates"]:
                assert set(item) == {"rank", "text"}
                assert item["text"] == original[item["rank"] - 1].text
            seen.extend(item["rank"] for item in body["candidates"])
            return httpx.Response(
                200, json={"scores": [{"rank": item["rank"], "score": 1} for item in reversed(body["candidates"])]}
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await HTTPMemoryReranker("https://test.invalid", client=client, batch_size=batch_size).rerank(
                "q", original, limit
            )
            assert not client.is_closed
        assert result.selected_ranks == tuple(range(1, limit + 1))
        assert result.usage.requests == (5 + batch_size - 1) // batch_size
        assert sorted(seen) == list(range(1, 6))
        assert tuple(hit.model_dump() for hit in original) == snapshot

    asyncio.run(run())


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"scores": {}},
        {"scores": []},
        {"scores": [{"rank": True, "score": 1}]},
        {"scores": [{"rank": 1.0, "score": 1}]},
        {"scores": [{"rank": 1, "score": True}]},
        {"scores": [{"rank": 1, "score": "1"}]},
        {"scores": [{"rank": 1, "score": float("-inf")}]},
        {"scores": [{"rank": 2, "score": 1}]},
    ],
)
def test_invalid_payload(payload):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=json.dumps(payload)))
        ) as client:
            with pytest.raises(ValueError):
                await HTTPMemoryReranker("https://test.invalid", client=client, batch_size=1).rerank("q", hits(), 1)

    asyncio.run(run())


@pytest.mark.parametrize("status", [400, 500])
def test_http_status(status):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(status))) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await HTTPMemoryReranker("https://test.invalid", client=client).rerank("q", hits(), 1)

    asyncio.run(run())


def test_invalid_json_and_parameters():
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"{"))
        ) as client:
            for size in (0, -1, True, 1.5):
                with pytest.raises(ValueError):
                    HTTPMemoryReranker("https://test.invalid", client=client, batch_size=size)
            reranker = HTTPMemoryReranker("https://test.invalid", client=client)
            for limit in (0, -1, 6, True, 1.5):
                with pytest.raises(ValueError):
                    await reranker.rerank("q", hits(), limit)
            with pytest.raises(ValueError):
                await reranker.rerank("q", hits(), 1)

    asyncio.run(run())
