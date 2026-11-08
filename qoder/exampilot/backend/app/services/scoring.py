"""Deterministic grading for objective question types.

No LLM is involved: correctness is computed with exact rules so the grading
evidence is reproducible and auditable.

Supported types: single_choice, multi_choice, true_false, short_answer.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

CHOICE_LETTER_RE = re.compile(r"^([A-H])\b", re.IGNORECASE)
LETTER_AFTER_SEP_RE = re.compile(r"(?:^|[\s：:，,、.])([A-H])\b", re.IGNORECASE)

_TRUE_WORDS = {"t", "true", "对", "正确", "是", "√", "✓", "yes", "y", "1"}
_FALSE_WORDS = {"f", "false", "错", "错误", "否", "×", "✗", "no", "n", "0"}
_LETTERS_RE = re.compile(r"^[A-H](?:[,，、;；\s]*[A-H])*$", re.IGNORECASE)

SHORT_ANSWER_THRESHOLD = 0.6


@dataclass
class GradingResult:
    is_correct: bool
    score: float
    evidence: str


def _clean(value: str) -> str:
    return re.sub(r"\s+", "", value.strip().lower())


def _extract_letters(value: str) -> list[str]:
    clean = _clean(value)
    if not clean:
        return []
    if _LETTERS_RE.match(clean):
        return re.findall(r"[a-h]", clean)
    m = CHOICE_LETTER_RE.match(clean) or LETTER_AFTER_SEP_RE.search(clean)
    if m:
        return [m.group(1)]
    return []


def _parse_options(options: str | None) -> list[tuple[str, str]]:
    if not options:
        return []
    try:
        raw = json.loads(options)
    except (TypeError, ValueError):
        return []
    parsed: list[tuple[str, str]] = []
    for idx, item in enumerate(raw):
        if isinstance(item, dict):
            letter = str(item.get("letter", "")).strip().upper()
            text = str(item.get("text", "")).strip()
        else:
            letter = chr(ord("A") + idx)
            text = str(item).strip()
        parsed.append((letter, text))
    return parsed


def grade_question(
    question_type: str,
    answer: str,
    options: str | None,
    user_answer: str,
) -> GradingResult:
    qtype = (question_type or "").strip().lower()
    ref = (answer or "").strip()
    user = (user_answer or "").strip()
    if qtype in ("single_choice", "single"):
        return _grade_single(ref, options, user)
    if qtype in ("multi_choice", "multiple"):
        return _grade_multi(ref, user)
    if qtype in ("true_false", "judge"):
        return _grade_bool(ref, user)
    if qtype in ("short_answer", "fill"):
        return _grade_short(ref, user)
    return GradingResult(False, 0.0, f"unknown question type: {qtype}")


def _grade_single(ref: str, options: str | None, user: str) -> GradingResult:
    opts = _parse_options(options)
    ref_letters = _extract_letters(ref)
    ref_text = _clean(ref)
    if not ref_letters and opts:
        for letter, text in opts:
            if _clean(text) == ref_text:
                ref_letters = [letter]
                break
    user_letters = _extract_letters(user)
    user_text = _clean(user)
    if not user_letters and opts:
        for letter, text in opts:
            if _clean(text) == user_text:
                user_letters = [letter]
                break
    if not ref_letters:
        ok = ref_text == user_text
        return GradingResult(
            ok, 1.0 if ok else 0.0, f"exact text match (reference={ref!r})"
        )
    if not user_letters:
        return GradingResult(False, 0.0, f"no option letter detected in {user!r}")
    ok = user_letters[0] == ref_letters[0]
    return GradingResult(
        ok,
        1.0 if ok else 0.0,
        f"selected {user_letters[0]}, correct answer {ref_letters[0]}",
    )


def _grade_multi(ref: str, user: str) -> GradingResult:
    ref_set = set(_extract_letters(ref))
    user_set = set(_extract_letters(user))
    if not ref_set:
        return GradingResult(False, 0.0, "reference answer has no option letters")
    if not user_set:
        return GradingResult(False, 0.0, f"no option letters detected in {user!r}")
    ref_s = "".join(sorted(ref_set))
    user_s = "".join(sorted(user_set))
    if user_set == ref_set:
        return GradingResult(True, 1.0, f"exact match {{{user_s}}}")
    if user_set < ref_set:
        return GradingResult(
            False, 0.5, f"partial: selected {{{user_s}}} of {{{ref_s}}}"
        )
    return GradingResult(
        False, 0.0, f"mismatch: selected {{{user_s}}}, correct {{{ref_s}}}"
    )


def _normalize_bool(value: str) -> bool | None:
    v = _clean(value)
    if v in _TRUE_WORDS:
        return True
    if v in _FALSE_WORDS:
        return False
    return None


def _grade_bool(ref: str, user: str) -> GradingResult:
    ref_bool = _normalize_bool(ref)
    user_bool = _normalize_bool(user)
    if ref_bool is None:
        return GradingResult(False, 0.0, f"reference answer is not boolean: {ref!r}")
    if user_bool is None:
        return GradingResult(False, 0.0, f"answer is not boolean: {user!r}")
    ok = user_bool == ref_bool
    return GradingResult(
        ok, 1.0 if ok else 0.0, f"normalized {user!r}→{user_bool}, correct={ref_bool}"
    )


def _tokens(text: str) -> list[str]:
    low = text.lower()
    words = re.findall(r"[a-z0-9]+", low)
    cjk = re.findall(r"[\u4e00-\u9fff]", low)
    bigrams = [cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)]
    return words + bigrams


def _grade_short(ref: str, user: str) -> GradingResult:
    ref_tokens = set(_tokens(ref))
    if not ref_tokens:
        return GradingResult(False, 0.0, "reference answer is empty")
    user_tokens = set(_tokens(user))
    matched = ref_tokens & user_tokens
    coverage = len(matched) / len(ref_tokens)
    score = round(min(coverage, 1.0), 2)
    ok = coverage >= SHORT_ANSWER_THRESHOLD
    return GradingResult(
        ok,
        score,
        f"keyword coverage {coverage:.2f} (matched {len(matched)}/{len(ref_tokens)}, "
        f"threshold {SHORT_ANSWER_THRESHOLD})",
    )
