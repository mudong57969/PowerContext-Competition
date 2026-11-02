from sqlalchemy import String
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from powercontext.builtin.persistence.source_lifecycle import LIFECYCLE_GRAPHS, LIFECYCLE_HIDDEN_TOPICS
from powercontext.limits import MAX_ARTIFACT_ID_LENGTH, MAX_SCOPE_ID_LENGTH


def test_lifecycle_schema_preserves_native_identity_limits_and_binary_comparison() -> None:
    for table in (LIFECYCLE_GRAPHS, LIFECYCLE_HIDDEN_TOPICS):
        column_type = table.c.scope_id.type
        assert isinstance(column_type, String)
        assert column_type.length == MAX_SCOPE_ID_LENGTH
        ddl = str(CreateTable(table).compile(dialect=mysql.dialect()))
        assert f"scope_id VARCHAR({MAX_SCOPE_ID_LENGTH}) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin" in ddl
    column_type = LIFECYCLE_HIDDEN_TOPICS.c.artifact_id.type
    assert isinstance(column_type, String)
    assert column_type.length == MAX_ARTIFACT_ID_LENGTH
