"""Single-statement candidate retrieval for the embedded seekdb profile."""

from __future__ import annotations

from pyobvector import VECTOR
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql.elements import TextClause
from typing_extensions import override

from powercontext.builtin.artifacts.memory import (
    CapabilityNotSupportedError,
    EmbeddingProfile,
    MemorySearchChannels,
    MemorySearchRequest,
)
from powercontext.builtin.artifacts.memory.canonical import validate_embedding
from powercontext.builtin.persistence.memory_index import CompositeMemoryIndex, memory_channel_hits
from powercontext.builtin.persistence.oceanbase.memory_index import (
    _OCEANBASE_VECTOR_SEARCH_SQL,
    OceanBaseMemoryFTSIndex,
    OceanBaseMemoryVectorIndex,
)
from powercontext.builtin.persistence.tags import memory_tag_parameters, memory_tag_sql

_FTS_SQL = """
SELECT
    f.memory_artifact_id, f.head_revision, f.entry_id, f.entry_version_id,
    v.text, NULL AS distance, 'fts' AS channel,
    MATCH(f.searchable_text) AGAINST (:query) AS fts_score
FROM pc_memory_entry_heads AS f
JOIN pc_memory_entry_versions AS v
  ON v.scope_id = f.scope_id
 AND v.memory_artifact_id = f.memory_artifact_id
 AND v.entry_version_id = f.entry_version_id
WHERE f.scope_id = :scope_id
  AND f.memory_artifact_id IN :memory_artifact_ids
  AND MATCH(f.searchable_text) AGAINST (:query)
{tags}
ORDER BY fts_score DESC, f.memory_artifact_id, f.entry_id, f.entry_version_id
LIMIT :candidate_limit
"""


_TAGGED_VECTOR_FROM_SQL = """
FROM pc_memory_vector_entries AS m
JOIN (
    SELECT tags.artifact_id, tags.target_id
    FROM pc_artifact_tags AS tags
    WHERE tags.scope_id = :scope_id
      AND tags.family = 'memory'
      AND tags.artifact_id IN :memory_artifact_ids
      AND tags.target_type = 'memory_entry'
      AND tags.tag_key_hash IN :tag_hashes
      AND tags.tag_key IN :tag_keys
    GROUP BY tags.artifact_id, tags.target_id
    HAVING COUNT(*) >= :tag_minimum
) AS eligible
  ON eligible.artifact_id = m.memory_artifact_id
 AND eligible.target_id = m.entry_id
"""


class SeekDBMemoryIndex(CompositeMemoryIndex):
    """Retain existing projections and single channels; combine hybrid candidates."""

    def __init__(self, profile: EmbeddingProfile) -> None:
        self.fts = OceanBaseMemoryFTSIndex()
        self.vector = OceanBaseMemoryVectorIndex(profile)
        super().__init__(self.fts, self.vector)
        self._hybrid_sql = self._statement(profile, tagged=False)
        self._tagged_hybrid_sql = self._statement(profile, tagged=True)

    @staticmethod
    def _statement(profile: EmbeddingProfile, *, tagged: bool) -> TextClause:
        fts = _FTS_SQL.format(tags=memory_tag_sql("f") if tagged else "")
        vector = _OCEANBASE_VECTOR_SEARCH_SQL.replace(
            " AS distance", " AS distance, 'vector' AS channel, NULL AS fts_score"
        )
        if tagged:
            # Join eligible identities before ANN; correlated post-filters can exhaust its candidate budget.
            vector = vector.replace("FROM pc_memory_vector_entries AS m", _TAGGED_VECTOR_FROM_SQL)
        statement = text(
            f"SELECT * FROM ({fts}) AS fts_candidates "  # noqa: S608 -- only internal SQL fragments; values stay bound
            f"UNION ALL SELECT * FROM ({vector}) AS vector_candidates "
            "ORDER BY channel, fts_score DESC, distance, memory_artifact_id, entry_id, entry_version_id"
        ).bindparams(
            bindparam("memory_artifact_ids", expanding=True),
            bindparam("query_vector", type_=VECTOR(profile.dimension)),
        )
        if tagged:
            statement = statement.bindparams(
                bindparam("tag_keys", expanding=True), bindparam("tag_hashes", expanding=True)
            )
        return statement

    @override
    async def search(
        self, connection: AsyncConnection, scope_id: str, request: MemorySearchRequest, /
    ) -> MemorySearchChannels:
        if request.mode == "fts":
            return await self.fts.search(connection, scope_id, request)
        if request.mode == "vector":
            return await self.vector.search(connection, scope_id, request)
        if request.embedding_profile != self.vector.profile or request.query_vector is None:
            raise CapabilityNotSupportedError("embedding-profile")
        if not await self.vector.vector_complete(connection, scope_id, request.memories, self.vector.profile):
            raise CapabilityNotSupportedError("vector")
        rows = (
            (
                await connection.execute(
                    self._hybrid_sql if request.tag_filter is None else self._tagged_hybrid_sql,
                    {
                        "scope_id": scope_id,
                        "memory_artifact_ids": tuple(memory.artifact_id for memory in request.memories),
                        "query": request.analyzed_query,
                        "query_vector": validate_embedding(
                            request.query_vector, dimension=self.vector.profile.dimension
                        ),
                        "candidate_limit": request.candidate_limit,
                        **memory_tag_parameters(request.tag_filter),
                    },
                )
            )
            .mappings()
            .all()
        )
        return MemorySearchChannels(
            fts=memory_channel_hits((row for row in rows if row["channel"] == "fts"), request.memories),
            vector=memory_channel_hits((row for row in rows if row["channel"] == "vector"), request.memories),
        )
