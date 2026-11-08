"""Unit tests for VECTOR literal serialization."""

from app.retrieval.vector_format import parse_vector_literal, vector_literal


def test_basic():
    assert vector_literal([0.1, 0.25, 1.0]) == "[0.1,0.25,1]"


def test_negative_and_precision():
    assert vector_literal([-0.5, 0.123456789]) == "[-0.5,0.123457]"


def test_empty():
    assert vector_literal([]) == "[]"


def test_parse_roundtrip():
    vec = [0.1, -0.25, 1.0]
    assert parse_vector_literal(vector_literal(vec)) == vec


def test_parse_plain_and_empty():
    assert parse_vector_literal("[]") == []
    assert parse_vector_literal("") == []
    assert parse_vector_literal("0.1,0.2") == [0.1, 0.2]
