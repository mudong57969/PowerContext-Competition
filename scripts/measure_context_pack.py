"""Measure actual incremental wire costs on the two published QMSum turns.

Run from the repository root: python scripts/measure_context_pack.py
This is a public sample measurement, not the formal 40-round acceptance.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import platform
from pathlib import Path

from powercontext.builtin.artifacts.memory import MemoryCandidateRequest, MemoryEntryInput
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    ContextPack,
    ContextPackDelta,
    PrepareContextRequest,
    apply_context_pack_delta,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.builtin.sources import ContentSource

_SAMPLE_PATH = (
    Path(__file__).resolve().parents[1]
    / "competition/challenges/context-02-incremental-pack/workload/public/turns.json"
)


class CandidatePipeline:
    async def extract(self, request: MemoryCandidateRequest, /) -> tuple[MemoryEntryInput, ...]:
        return tuple(
            MemoryEntryInput(kind="conversation-turn", text=source.content, sources=(source,))
            for source in request.sources
            if isinstance(source, ContentSource)
        )


def chunk_costs(bodies: list[str]) -> dict[str, int]:
    """Compare bounded line-aware chunks and fixed-width chunks on identical bodies."""
    costs = {}
    for limit in (64, 128, 256, 512, 1024):
        previous = None
        cost = 0
        for content in bodies:
            target = ContextPack.from_content(content, chunk_bytes=limit)
            message = target if previous is None else ContextPackDelta.between(previous, target)
            cost += len(message.to_bytes())
            previous = target
        costs[str(limit)] = cost
    previous = None
    fixed_cost = 0
    for content in bodies:
        # Published sample bodies are ASCII; slicing is a valid fixed-width comparison.
        raw = content.encode("utf-8")
        target = ContextPack.build(tuple(raw[index : index + 512] for index in range(0, len(raw), 512)))
        message = target if previous is None else ContextPackDelta.between(previous, target)
        fixed_cost += len(message.to_bytes())
        previous = target
    costs["fixed_512"] = fixed_cost
    return costs


async def main() -> None:
    sample = json.loads(await asyncio.to_thread(_SAMPLE_PATH.read_text, encoding="utf-8"))
    rows: list[dict[str, int]] = []
    base = None
    bodies = []
    async with open_builtin_runtime(BuiltinConfig(), candidate_pipeline=CandidatePipeline()) as runtime:
        if runtime.scopes is None:
            raise RuntimeError("Runtime scopes unavailable")  # noqa: TRY003
        scope = await runtime.scopes.create(
            ScopeDraft(title="Incremental pack", summary="Public sample costs", idempotency_key="pack-measurement")
        )
        context = runtime.context.for_scope(scope.scope_id)
        for number, turn in enumerate(sample["turns"], 1):
            await runtime.sources.for_scope(scope.scope_id).capture(
                CaptureSource(source_id=f"turn-{number}", content=turn["text"], metadata={})
            )
            while (await runtime.memory.for_scope(scope.scope_id).flush()).processed:
                pass
            request = PrepareContextRequest(query=sample["query"], max_bytes=4096)
            prepared = await context.prepare(request)
            body = (prepared.content or "").encode("utf-8")
            bodies.append(body.decode())
            full = ContextPack.from_content(body.decode())
            message = await context.prepare_incremental(request, base_pack=base)
            wire = message.to_bytes()
            if isinstance(message, ContextPackDelta):
                if base is None:
                    raise RuntimeError("Delta without base")  # noqa: TRY003
                base = apply_context_pack_delta(base, ContextPackDelta.from_bytes(wire))
            else:
                base = ContextPack.from_bytes(wire)
            if b"".join(base.items) != body or base != full:
                raise RuntimeError("Independent replay differs from prepare")  # noqa: TRY003
            rows.append({
                "round": number,
                "raw_full_bytes": len(body),
                "incremental_bytes": len(wire),
                "full_pack_bytes": len(full.to_bytes()),
                "gzip_bytes": len(gzip.compress(body, compresslevel=9, mtime=0)),
                "prefix_items": message.prefix_items if isinstance(message, ContextPackDelta) else 0,
            })
    totals = {
        key: sum(row[key] for row in rows)
        for key in ("raw_full_bytes", "incremental_bytes", "full_pack_bytes", "gzip_bytes")
    }
    savings = {
        key: 1 - totals["incremental_bytes"] / totals[key]
        for key in ("raw_full_bytes", "full_pack_bytes", "gzip_bytes")
    }
    common = 0
    for left, right in zip(bodies[0].encode(), bodies[1].encode(), strict=False):
        if left != right:
            break
        common += 1
    # Optimistic lower bound excludes all metadata and Base64 padding overhead.
    suffix_lower_bound = len(bodies[0].encode()) + len(bodies[1].encode()) - common
    print(
        json.dumps(
            {
                "sample": _SAMPLE_PATH.relative_to(_SAMPLE_PATH.parents[5]).as_posix(),
                "formal_40_rounds": False,
                "python": platform.python_version(),
                "platform": platform.system(),
                "query": sample["query"],
                "max_bytes": 4096,
                "chunk_bytes": 512,
                "rounds": rows,
                "totals": totals,
                "savings": savings,
                "chunk_limit_wire_bytes": chunk_costs(bodies),
                "body_common_prefix_bytes": common,
                "optimistic_unencoded_transmission_lower_bound": suffix_lower_bound,
                "prepared_contents": bodies,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
