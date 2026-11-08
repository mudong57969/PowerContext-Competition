"""Unit tests for seekdb FULLTEXT tokenization (trigram expansion)."""

from app.retrieval.fts_text import MIN_TOKEN_CHARS, fts_tokenize


def test_cjk_run_expands_to_full_run_plus_trigrams():
    # 4-char run: full run + (4-2) overlapping trigrams
    assert fts_tokenize("动态功耗") == "动态功耗 动态功 态功耗"
    # 6-char run: full run + (6-2) overlapping trigrams
    assert fts_tokenize("动态功耗公式") == "动态功耗公式 动态功 态功耗 功耗公 耗公式"


def test_three_char_run_is_full_run_only():
    assert fts_tokenize("反相器") == "反相器 反相器"


def test_short_cjk_run_produces_no_tokens():
    # seekdb drops tokens shorter than 3 chars, so 1-2 char runs contribute nothing
    assert MIN_TOKEN_CHARS == 3
    assert fts_tokenize("功耗") == ""
    assert fts_tokenize("由") == ""


def test_ascii_words_pass_through_lowercased():
    assert fts_tokenize("CMOS inverter VDD") == "cmos inverter vdd"


def test_mixed_cjk_and_ascii():
    out = fts_tokenize("MOS 阈值电压 VT 由衬底掺杂决定")
    assert out.startswith("mos 阈值电压 阈值电 值电压 vt 由衬底掺杂决定")
    assert "由衬底" in out
    assert out.endswith("杂决定")


def test_empty_and_punctuation_only():
    assert fts_tokenize("") == ""
    assert fts_tokenize("！！！###") == ""


def test_adjacent_cjk_runs_separated_by_punctuation():
    # "功耗" (2 chars) is dropped; "泄漏功耗" (4 chars) is expanded
    out = fts_tokenize("功耗。泄漏功耗")
    assert out == "泄漏功耗 泄漏功 漏功耗"
