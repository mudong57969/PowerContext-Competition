"""Unit tests for deterministic question grading."""

import pytest

from app.services.scoring import (
    _extract_letters,
    _grade_bool,
    _grade_multi,
    _grade_short,
    _grade_single,
    _normalize_bool,
    _parse_options,
    grade_question,
)

OPTIONS_JSON = '[{"letter": "A", "text": "选项一"}, {"letter": "B", "text": "选项二"}, {"letter": "C", "text": "选项三"}]'


class TestExtractLetters:
    def test_single(self):
        assert _extract_letters("A") == ["a"]
        assert _extract_letters(" b ") == ["b"]

    def test_multiple(self):
        assert _extract_letters("ABD") == ["a", "b", "d"]
        assert _extract_letters("A、C") == ["a", "c"]

    def test_answer_with_prefix(self):
        assert _extract_letters("A. 选项一") == ["a"]
        assert _extract_letters("答案：B") == ["b"]

    def test_no_letter(self):
        assert _extract_letters("") == []
        assert _extract_letters("这是文字") == []
        assert _extract_letters("这是A项") == []


class TestParseOptions:
    def test_dict_form(self):
        assert _parse_options(OPTIONS_JSON) == [
            ("A", "选项一"),
            ("B", "选项二"),
            ("C", "选项三"),
        ]

    def test_list_form_gets_implicit_letters(self):
        assert _parse_options('["x", "y"]') == [("A", "x"), ("B", "y")]

    def test_invalid(self):
        assert _parse_options(None) == []
        assert _parse_options("not json") == []


class TestGradeSingle:
    def test_correct_and_wrong(self):
        ok = _grade_single("A", OPTIONS_JSON, "A")
        assert ok.is_correct and ok.score == 1.0
        bad = _grade_single("A", OPTIONS_JSON, "B")
        assert not bad.is_correct and bad.score == 0.0

    def test_user_full_option_text_matches(self):
        ok = _grade_single("A", OPTIONS_JSON, "选项二")
        assert not ok.is_correct
        # reference stored as option text itself
        ok2 = _grade_single("选项二", OPTIONS_JSON, "选项二")
        assert ok2.is_correct

    def test_no_letter_detected(self):
        res = _grade_single("A", OPTIONS_JSON, "不知道")
        assert not res.is_correct and res.score == 0.0
        assert "no option letter" in res.evidence


class TestGradeMulti:
    def test_exact(self):
        assert _grade_multi("ABD", "BAD").is_correct
        assert _grade_multi("ABD", "D、A、B").is_correct

    def test_partial_subset_scores_half(self):
        res = _grade_multi("ABD", "AB")
        assert not res.is_correct and res.score == 0.5

    def test_extra_letter_scores_zero(self):
        res = _grade_multi("AB", "ABC")
        assert not res.is_correct and res.score == 0.0

    def test_empty(self):
        assert _grade_multi("AB", "").score == 0.0
        assert _grade_multi("", "A").score == 0.0


class TestGradeBool:
    @pytest.mark.parametrize(
        "ref,user,expected",
        [
            ("对", "√", True),
            ("对", "正确", True),
            ("T", "true", True),
            ("1", "是", True),
            ("错", "×", True),
            ("F", "false", True),
            ("0", "否", True),
            ("对", "错", False),
            ("true", "false", False),
        ],
    )
    def test_normalization(self, ref, user, expected):
        assert _grade_bool(ref, user).is_correct is expected

    def test_unparseable_user(self):
        res = _grade_bool("对", "maybe")
        assert not res.is_correct and "not boolean" in res.evidence

    def test_unparseable_ref(self):
        res = _grade_bool("maybe", "对")
        assert not res.is_correct

    def test_normalize_bool(self):
        assert _normalize_bool("√") is True
        assert _normalize_bool("✗") is False
        assert _normalize_bool("N") is False
        assert _normalize_bool("xyz") is None


class TestGradeShort:
    def test_full_keyword_overlap(self):
        res = _grade_short("动态功耗公式", "动态功耗公式")
        assert res.is_correct and res.score == 1.0

    def test_partial_coverage_below_threshold(self):
        res = _grade_short("传播延迟由负载电容决定", "传播延迟")
        assert not res.is_correct
        assert 0.0 < res.score < 0.6

    def test_empty_reference(self):
        res = _grade_short("", "anything")
        assert not res.is_correct and res.score == 0.0

    def test_ascii_tokens(self):
        res = _grade_short(
            "propagation delay depends on load", "propagation delay load"
        )
        assert res.is_correct


class TestDispatch:
    def test_unknown_type(self):
        res = grade_question("essay", "x", None, "y")
        assert not res.is_correct and res.score == 0.0
        assert "unknown question type" in res.evidence

    def test_true_false_aliases(self):
        assert grade_question("judge", "对", None, "对").is_correct
        assert grade_question("true_false", "F", None, "false").is_correct
