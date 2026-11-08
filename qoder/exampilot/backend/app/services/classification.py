"""Automatic course/chapter/knowledge-point classification.

Deterministic, evidence-based classification. Confidence is a computed score
from real evidence signals (title/headings, body keywords with occurrence
density, filename as a weak prior, retrieval similarity against the existing
knowledge base) — not a model's self-reported confidence.

Terminology matching normalizes text (lowercase, whitespace/hyphen folding)
so Chinese and English synonyms are treated uniformly. ASCII terms are
matched with word boundaries (so ``tp`` never matches inside ``output``);
CJK terms are matched as substrings.

Decision thresholds are configurable (see Settings.classify_*_confidence):
  confidence >= high  -> auto-filed
  high > conf >= mid  -> suggested (one-click confirm)
  conf < mid          -> pending review (candidates + reason are returned)

Failure reasons distinguish:
  insufficient_text  — not enough extractable text to classify at all
  no_signal          — text extracted but no lexicon/heading signal matched
  new_course         — heading suggests a course not in lexicon / not existing
  ambiguous          — top candidates too close to call
  ok                 — classified normally (may still be below thresholds)

A configurable LLM hook could be added here later (classify via the LLM
provider when ``llm_provider`` is enabled); until a model is configured the
classifier stays fully deterministic.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.core.seekdb import get_engine
from app.retrieval.fts_text import fts_tokenize
from app.services.parsing import MIN_TEXT_CHARS, ParseResult

# --- domain lexicon (extensible) ------------------------------------------
# Chinese + English keyword signals per course/chapter/knowledge point.
DOMAIN_COURSE_KEYWORDS: dict[str, list[str]] = {
    "数字集成电路": [
        "数字集成电路",
        "digital integrated circuit",
        "cmos",
        "vlsi",
        "反相器",
        "inverter",
        "mos",
        "晶体管",
        "transistor",
        "半导体",
        "semiconductor",
        "阈值电压",
        "threshold voltage",
        "功耗",
        "power",
        "传播延迟",
        "propagation delay",
        "互连",
        "interconnect",
        "噪声容限",
        "noise margin",
        "集成电路",
        "integrated circuit",
    ],
    "数字信号处理": [
        "数字信号处理",
        "digital signal processing",
        "dsp",
        "离散傅里叶",
        "discrete fourier",
        "dft",
        "fft",
    ],
    "概率论": [
        "概率论",
        "probability",
        "随机变量",
        "random variable",
        "分布",
        "distribution",
    ],
    "模拟集成电路": [
        "模拟集成电路",
        "analog integrated circuit",
        "运算放大器",
        "operational amplifier",
        "opamp",
    ],
    "嵌入式系统": ["嵌入式系统", "embedded system", "单片机", "microcontroller", "mcu"],
}

DOMAIN_CHAPTER_KEYWORDS: dict[str, list[str]] = {
    "数字集成电路": {
        "MOS 器件": [
            "mos 器件",
            "mos device",
            "晶体管",
            "transistor",
            "阈值电压",
            "threshold voltage",
            "工作区",
            "operating region",
            "速度饱和",
            "velocity saturation",
            "短沟道",
            "short-channel",
            "short channel",
            "体效应",
            "body effect",
            "沟道长度调制",
            "channel length modulation",
            "i-v",
            "iv characteristics",
            "阈值变化",
            "threshold variation",
        ],
        "CMOS 反相器": [
            "cmos 反相器",
            "cmos inverter",
            "vtc",
            "电压传输特性",
            "voltage transfer",
            "噪声容限",
            "noise margin",
            "反相器",
            "inverter",
        ],
        "功耗": [
            "功耗",
            "power",
            "动态功耗",
            "dynamic power",
            "短路功耗",
            "short-circuit",
            "泄漏功耗",
            "leakage power",
            "亚阈值",
            "subthreshold",
            "能量",
            "energy",
        ],
        "互连线": ["互连线", "interconnect", "rc 延迟", "rc delay", "导线", "wire"],
        "工艺与缩放": [
            "工艺与缩放",
            "scaling",
            "尺寸缩放",
            "功耗密度",
            "power density",
            "工艺",
            "process technology",
        ],
    },
}

DOMAIN_KP_KEYWORDS: dict[str, list[str]] = {
    "数字集成电路": [
        (
            "MOS 阈值电压",
            [
                "阈值电压",
                "threshold voltage",
                "vth",
                "vt0",
                "阈值变化",
                "threshold variation",
                "threshold shift",
                "dibl",
            ],
        ),
        (
            "MOS 工作区",
            [
                "截止区",
                "线性区",
                "饱和区",
                "cutoff region",
                "saturation region",
                "triode",
                "pinch off",
            ],
        ),
        (
            "体效应",
            [
                "体效应",
                "body effect",
                "源衬电压",
                "source bulk",
                "衬底偏置",
                "substrate bias",
                "body bias",
            ],
        ),
        (
            "沟道长度调制",
            [
                "沟道长度调制",
                "channel length modulation",
                "厄尔利",
                "early effect",
                "沟道长度",
            ],
        ),
        (
            "速度饱和",
            ["速度饱和", "velocity saturation", "载流子速度", "carrier velocity"],
        ),
        (
            "短沟道效应",
            [
                "短沟道效应",
                "short-channel effect",
                "short channel effect",
                "short-channel",
                "短沟道",
            ],
        ),
        (
            "CMOS VTC",
            [
                "vtc",
                "电压传输特性",
                "voltage transfer characteristic",
                "噪声容限",
                "noise margin",
            ],
        ),
        ("传播延迟", ["传播延迟", "propagation delay", "tp", "tphl", "tplh"]),
        (
            "动态功耗",
            ["动态功耗", "dynamic power", "开关功耗", "switching power", "p=α"],
        ),
        (
            "短路功耗",
            ["短路功耗", "short-circuit power", "直流通路", "simultaneous conduction"],
        ),
        (
            "泄漏功耗",
            [
                "泄漏功耗",
                "leakage power",
                "亚阈值",
                "subthreshold",
                "静态功耗",
                "static power",
                "泄漏电流",
                "leakage current",
                "漏电",
            ],
        ),
        ("互连延迟", ["互连延迟", "interconnect delay", "rc delay", "elmore"]),
        ("扇出与扇入", ["扇出", "扇入", "fanout", "fan in", "fan-out"]),
        (
            "尺寸缩放与功耗密度",
            ["尺寸缩放", "功耗密度", "scaling", "power density", "dennard"],
        ),
    ],
}

CHAPTER_HEADING_RE = re.compile(
    r"^(chapter|ch\.?|chap\.?)\s*(\d+|[ivxlc]+)\s*[:：\-]?\s*(.*)$", re.IGNORECASE
)
CN_CHAPTER_RE = re.compile(r"^第\s*([0-9一二三四五六七八九十]+)\s*章\s*[:：]?\s*(.*)$")

PAGE_NUMBER_RE = re.compile(r"^\s*\d+\s*/\s*\d+\s*$")
TITLE_MAX_LEN = 60

# Bumped whenever the classification logic changes; persisted in the evidence
# of every classification so old results can be told apart from new ones.
CLASSIFIER_VERSION = "3.1"

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
ASCII_TERM_RE_CACHE: dict[str, re.Pattern] = {}


def _norm(text: str) -> str:
    """Lowercase, fold hyphens/vertical-tabs, tighten operators, collapse whitespace."""
    text = text.replace("\x0b", " ").replace("\u00a0", " ")
    text = re.sub(r"[-\u2010\u2011\u2012\u2013\u2014]", " ", text)
    text = re.sub(r"\s*=\s*", "=", text)
    text = re.sub(r"\s+", " ", text)
    return text.lower().strip()


def _is_cjk(s: str) -> bool:
    return bool(CJK_RE.search(s))


def _term_re(keyword: str) -> re.Pattern:
    pat = ASCII_TERM_RE_CACHE.get(keyword)
    if pat is None:
        pat = re.compile(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])")
        ASCII_TERM_RE_CACHE[keyword] = pat
    return pat


def _count_term(norm_text: str, keyword: str) -> int:
    if not keyword:
        return 0
    if _is_cjk(keyword):
        return norm_text.count(keyword)
    return len(_term_re(keyword).findall(norm_text))


def _keyword_signal(text: str, keywords: list[str], title_text: str = "") -> dict:
    """Weighted evidence score: presence of distinct terms + occurrence density.

    Returns a dict with score in [0, 1], presence count and total weight so
    callers (and the stored evidence) can see how the score was derived.
    """
    norm, norm_title = _norm(text), _norm(title_text)
    presence = 0
    weight = 0.0
    for kw in keywords:
        body = _count_term(norm, kw)
        title = _count_term(norm_title, kw)
        if body or title:
            presence += 1
            weight += 1.0 + min(1.0, math.log2(1 + body) / 3)
            if title:
                weight += 0.8
    denom_p = max(2.0, len(keywords) * 0.35)
    denom_w = max(3.0, len(keywords) * 0.7)
    score = 0.55 * min(1.0, presence / denom_p) + 0.45 * min(1.0, weight / denom_w)
    return {"score": round(score, 4), "presence": presence, "weight": round(weight, 2)}


def _keyword_score(text: str, keywords: list[str]) -> float:
    """Legacy presence-ratio score (kept for compatibility)."""
    return _keyword_signal(text, keywords)["score"]


def _rank_keyword_sets(
    text: str, sets: dict[str, list[str]], title_text: str = ""
) -> list[tuple[str, float]]:
    ranked = []
    for name, keywords in sets.items():
        ranked.append((name, _keyword_signal(text, keywords, title_text)["score"]))
    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked


def _match_keyword_sets(text: str, sets: dict[str, list[str]]) -> tuple[str, float]:
    ranked = _rank_keyword_sets(text, sets)
    if not ranked:
        return None, 0.0
    return ranked[0]


TITLE_NOISE = {
    "outline",
    "目录",
    "contents",
    "agenda",
    "overview",
    "summary",
    "总结",
    "introduction",
    "导论",
    "review",
}


def _derive_title(text: str) -> str | None:
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"\s*\d+\s*/\s*\d+\s*$", "", line).strip()
        if not line or PAGE_NUMBER_RE.match(line):
            continue
        if len(line) <= TITLE_MAX_LEN:
            return line
        return None
    return None


def _extract_headings(pages: list) -> list[str]:
    headings: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        key = name.strip().strip("#").strip()
        if key and key not in seen:
            seen.add(key)
            headings.append(name)

    for page in pages:
        if page.section:
            add(page.section)
        derived = _derive_title(page.text)
        if derived and (not page.section or derived != page.section):
            add(derived)
        for line in page.text.split("\n"):
            if re.match(r"^(#{1,6}\s)", line):
                add(line.lstrip("#").strip())
    return headings


def _chapter_from_patterns(text: str) -> tuple[str | None, float]:
    for line in text.split("\n"):
        m = CHAPTER_HEADING_RE.match(line.strip())
        if m:
            name = m.group(3).strip()
            return (name or f"Chapter {m.group(2)}"), 0.9
        m = CN_CHAPTER_RE.match(line.strip())
        if m:
            name = m.group(2).strip()
            return (name or f"第{m.group(1)}章"), 0.9
    return None, 0.0


def _chapter_from_keywords(
    text: str, course: str, title_text: str = ""
) -> tuple[str | None, float]:
    sets = DOMAIN_CHAPTER_KEYWORDS.get(course)
    if not sets:
        return None, 0.0
    ranked = _rank_keyword_sets(text, sets, title_text)
    if not ranked:
        return None, 0.0
    name, score = ranked[0]
    if score >= 0.4:
        return name, min(score * 1.5, 0.85)
    return None, 0.0


def _kps_with_evidence(pages: list, course: str) -> list[dict]:
    """Knowledge points found in the content, with slide numbers as evidence.

    Courses covered by the domain lexicon use curated keyword sets; every
    other course falls back to generic structured-heading extraction. A page
    counts as evidence for a lexicon KP when its keyword signal is strong
    (>= 0.4) — or when at least two pages show a moderate signal (>= 0.25).
    """
    entries = DOMAIN_KP_KEYWORDS.get(course, [])
    found: list[dict] = []
    for name, keywords in entries:
        strong: list[int] = []
        moderate: list[int] = []
        for page in pages:
            title = page.section or _derive_title(page.text) or ""
            sig = _keyword_signal(page.text, keywords, title)
            if sig["score"] >= 0.4:
                strong.append(page.page_number)
            elif sig["score"] >= 0.25:
                moderate.append(page.page_number)
        if strong or len(moderate) >= 2:
            slides = strong + [n for n in moderate if n not in strong]
            found.append({"name": name, "slides": slides})
    if not found:
        found = _generic_kps_with_evidence(pages, course)
    return found


GENERIC_KP_STOP = set("。！？…；，、:：!?,;")
GENERIC_KP_MAX = 8


def _term_like_heading(name: str) -> bool:
    n = name.strip().strip("#").strip()
    if not (2 <= len(n) <= 24):
        return False
    if PAGE_NUMBER_RE.match(n):
        return False
    if any(ch in n for ch in GENERIC_KP_STOP):
        return False
    if n.count(" ") >= 3:
        return False
    if n.lower() in TITLE_NOISE:
        return False
    return _chapter_from_patterns(n)[0] is None


def _generic_kps_with_evidence(pages: list, course: str) -> list[dict]:
    """Term-like structured-heading candidates with real page evidence.

    Conservative on purpose: only short term-like headings (no sentence
    punctuation, no chapter patterns, not the course title itself) that are
    backed by at least two pages — one of them the heading's own section —
    become candidate knowledge points. Unreliable content yields nothing,
    leaving manual confirmation as the fallback.
    """
    headings = _extract_headings(pages)
    cands: list[dict] = []
    for h in headings:
        name = h.strip().strip("#").strip()
        if not _term_like_heading(name) or name == course:
            continue
        slides: list[int] = []
        own_section = False
        for page in pages:
            if (page.section or "").strip() == name:
                own_section = True
                slides.append(page.page_number)
            elif _norm(name) in _norm(page.text):
                slides.append(page.page_number)
        if not own_section or len(slides) < 2:
            continue
        if any(name in c["name"] for c in cands):
            continue
        cands.append({"name": name, "slides": slides})
    return cands[:GENERIC_KP_MAX]


def _kps_from_keywords(text: str, course: str) -> list[str]:
    """Legacy single-page wrapper (kept for compatibility)."""
    from app.services.parsing import ParsedPage

    pages = [ParsedPage(page_number=1, text=text)]
    return [kp["name"] for kp in _kps_with_evidence(pages, course)]


def _existing_courses(session_id: str) -> list[dict]:
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM courses WHERE session_id=%s", (session_id,))
        return [{"id": r[0], "name": r[1]} for r in cur.fetchall()]


def _existing_chapters(session_id: str, course_id: int | None) -> list[dict]:
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        if course_id is None:
            cur.execute(
                "SELECT c.id, c.name FROM chapters c JOIN courses co ON c.course_id=co.id WHERE co.session_id=%s",
                (session_id,),
            )
        else:
            cur.execute(
                "SELECT id, name FROM chapters WHERE course_id=%s", (course_id,)
            )
        return [{"id": r[0], "name": r[1]} for r in cur.fetchall()]


def _retrieval_signal(session_id: str, text: str) -> tuple[str | None, float]:
    """Fulltext search existing chunks; strong same-course matches support the course guess."""
    query = " ".join(fts_tokenize(text).split()[:32])
    if not query:
        return None, 0.0
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT co.name, COUNT(*) FROM document_chunks dc
                JOIN documents d ON dc.document_id = d.id
                JOIN courses co ON d.course_id = co.id
                WHERE d.session_id=%s AND MATCH(dc.fts_text) AGAINST (%s)
                GROUP BY co.name ORDER BY COUNT(*) DESC LIMIT 1
                """,
                (session_id, query),
            )
        except Exception:  # noqa: BLE001 - FTS probe is best-effort
            return None, 0.0
        row = cur.fetchone()
        if not row:
            return None, 0.0
        return row[0], min(row[1] / 5.0, 1.0)


def _filename_terms(filename: str) -> list[str]:
    stem = Path(filename).stem
    toks = re.split(r"[^A-Za-z0-9\u4e00-\u9fff]+", stem.lower())
    terms: list[str] = []
    for tok in toks:
        if len(tok) < 2:
            continue
        if re.fullmatch(
            r"(chapter|ch|chap|device|part|lec|lecture|section|sec|lab)?\d+", tok
        ):
            continue
        terms.append(tok)
    return terms


def _heading_course_candidate(headings: list[str], *, structural: bool) -> str | None:
    """A course-like name from the first meaningful heading (for new courses).

    ``structural`` is True when the document shows real structure (multiple
    headings, chapter patterns, or several pages) — a single unstructured
    page's first sentence is not treated as a course name.
    """
    if not structural:
        return None
    for h in headings:
        name = h.strip().strip("#").strip()
        if not name or PAGE_NUMBER_RE.match(name):
            continue
        name = re.sub(
            r"^(chapter|ch\.?|chap\.?)\s*\d+\s*[:：\-]?\s*",
            "",
            name,
            flags=re.IGNORECASE,
        )
        name = re.sub(r"^第\s*[0-9一二三四五六七八九十]+\s*章\s*[:：]?\s*", "", name)
        name = re.sub(r"^\d+[\.\)、:：]?\s*", "", name)
        if 2 <= len(name) <= 40 and name.lower() not in TITLE_NOISE:
            return name
    return None


@dataclass
class ClassifyEvidence:
    course: str | None
    course_confidence: float
    chapter: str | None
    chapter_confidence: float
    knowledge_points: list[str]
    signals: dict = field(default_factory=dict)


@dataclass
class ClassifyDecision:
    course: str | None
    chapter: str | None
    knowledge_points: list[str]
    confidence: float
    status: str  # auto | suggested | pending
    evidence: dict
    reason: str = "ok"
    course_candidates: list[dict] = field(default_factory=list)
    chapter_candidates: list[dict] = field(default_factory=list)
    kp_evidence: dict = field(default_factory=dict)


def classify_document(
    session_id: str,
    filename: str,
    parse_result: ParseResult,
    high_threshold: float,
    mid_threshold: float,
) -> ClassifyDecision:
    pages = parse_result.pages
    text = parse_result.full_text
    headings = _extract_headings(pages)
    heading_text = "\n".join(headings)
    all_signals_text = f"{heading_text}\n{text}"

    signals: dict = {}
    reason = "ok"

    # 0) not enough text at all -> cannot classify from content
    if parse_result.total_chars < MIN_TEXT_CHARS:
        evidence = {
            "course": None,
            "course_confidence": 0.0,
            "chapter": None,
            "chapter_confidence": 0.0,
            "knowledge_points": [],
            "course_candidates": [
                {"name": f"[{t}]", "score": 0.1, "source": "filename"}
                for t in _filename_terms(filename)[:3]
            ],
            "chapter_candidates": [],
            "status": "pending",
            "reason": "insufficient_text",
            "classifier_version": CLASSIFIER_VERSION,
            "signals": {"total_chars": parse_result.total_chars},
            "formula": "0.55*course + 0.30*chapter + 0.15*retrieval",
        }
        return ClassifyDecision(
            course=None,
            chapter=None,
            knowledge_points=[],
            confidence=0.0,
            status="pending",
            evidence=evidence,
            reason="insufficient_text",
            course_candidates=[
                {"name": f"[{t}]", "score": 0.1, "source": "filename"}
                for t in _filename_terms(filename)[:3]
            ],
        )

    # 1) course candidates from domain lexicon (title-weighted)
    ranked_courses = _rank_keyword_sets(
        all_signals_text, DOMAIN_COURSE_KEYWORDS, heading_text
    )
    course_candidates = [
        {"name": name, "score": round(score, 3), "source": "lexicon"}
        for name, score in ranked_courses[:4]
        if score > 0
    ]
    lex_course, lex_score = ranked_courses[0] if ranked_courses else (None, 0.0)
    if lex_score <= 0:
        lex_course = None
    signals["lexicon_course"] = {"name": lex_course, "score": round(lex_score, 3)}

    # 1b) filename is a weak prior only: it nudges matching candidates, never decides
    fname_terms = _filename_terms(filename)
    if fname_terms:
        for cand in course_candidates:
            kws = DOMAIN_COURSE_KEYWORDS.get(cand["name"], [])
            if any(t in _norm(" ".join(kws)) for t in fname_terms):
                cand["score"] = round(min(cand["score"] + 0.06, 1.0), 3)
        course_candidates.sort(key=lambda c: c["score"], reverse=True)

    # 2) heading-derived candidate for never-seen courses, computed BEFORE the
    # retrieval/existing-course signals: a reliable content course title must
    # outrank weak seekdb similarity, and existing courses must not
    # unconditionally override it. Requires real structure (several headings,
    # several pages, or a chapter pattern).
    structural = (
        len(headings) >= 2
        or len(pages) >= 2
        or bool(_chapter_from_patterns(heading_text)[0])
    )
    heading_course = _heading_course_candidate(headings, structural=structural)
    if heading_course:
        signals["heading_course"] = heading_course

    # 3) exact/near match against existing courses in this session. A mere
    # mention of an existing course name does not override a different,
    # structurally evidenced course title.
    existing = _existing_courses(session_id)
    course_name, course_confidence = lex_course, lex_score
    signals["existing_courses"] = [c["name"] for c in existing]
    heading_blocks_existing = bool(heading_course) and not any(
        heading_course.lower() in c["name"].lower()
        or c["name"].lower() in heading_course.lower()
        for c in existing
    )
    for c in existing:
        if c["name"].lower() in all_signals_text.lower() or lex_course == c["name"]:
            if heading_blocks_existing and lex_score < 0.25:
                signals["existing_course_mention_only"] = c["name"]
                continue
            course_name, course_confidence = c["name"], max(course_confidence, 0.95)
            signals["existing_course_match"] = c["name"]
            break
    # a different, structurally evidenced heading outranks a weak lexicon hit
    # that merely echoes the existing course name (existing must not
    # unconditionally override a new course)
    if (
        heading_blocks_existing
        and lex_score < 0.25
        and course_name is not None
        and lex_course == course_name
    ):
        signals["weak_lexicon_discarded"] = {
            "name": lex_course,
            "score": round(lex_score, 3),
        }
        course_name = None
        course_confidence = 0.0

    # 4) retrieval similarity is a weak auxiliary signal only: it fills in the
    # course when neither the lexicon nor a reliable heading produced one.
    ret_course, ret_score = _retrieval_signal(session_id, text)
    signals["retrieval_course"] = {"name": ret_course, "score": round(ret_score, 3)}
    if ret_course and course_name is None and not heading_course:
        course_name = ret_course
    if ret_course == course_name:
        course_confidence = max(course_confidence, 0.6 + 0.35 * ret_score)

    # 4b) adopt the heading-derived new course
    if course_name is None and heading_course and lex_score < 0.25:
        course_name = heading_course
        course_confidence = 0.4
        course_candidates.append(
            {"name": heading_course, "score": 0.4, "source": "heading"}
        )
        reason = "new_course"
    elif course_name is None and not course_candidates and heading_course:
        course_candidates.append(
            {"name": heading_course, "score": 0.3, "source": "heading"}
        )
        reason = "new_course"

    # 5) ambiguity among the top lexicon candidates
    if reason == "ok" and len(ranked_courses) >= 2:
        gap = ranked_courses[0][1] - ranked_courses[1][1]
        if (
            course_name is not None
            and gap < 0.08
            and ranked_courses[0][0] == course_name
        ):
            reason = "ambiguous"

    # 5b) filename-vs-content conflict: the filename points at a course the
    # content did not pick -> explicit reason (content wins)
    if reason == "ok" and fname_terms and course_name:
        chosen_kws = _norm(" ".join(DOMAIN_COURSE_KEYWORDS.get(course_name, [])))
        supports = any(t in chosen_kws for t in fname_terms)
        fname_courses = [
            name
            for name in DOMAIN_COURSE_KEYWORDS
            if any(
                t in _norm(" ".join(DOMAIN_COURSE_KEYWORDS[name])) for t in fname_terms
            )
        ]
        if not supports and fname_courses:
            reason = "filename_conflict"
            signals["filename_conflict"] = {
                "filename_terms": fname_terms,
                "filename_courses": fname_courses,
                "content_course": course_name,
            }

    # 6) chapter: explicit heading pattern first, then lexicon, then existing names
    chapter_name, chapter_conf = _chapter_from_patterns(heading_text)
    chapter_source = "pattern"
    signals["chapter_pattern"] = {"name": chapter_name, "score": round(chapter_conf, 3)}
    chapter_candidates: list[dict] = []
    if chapter_name is None and course_name:
        sets = DOMAIN_CHAPTER_KEYWORDS.get(course_name)
        if sets:
            ranked_chapters = _rank_keyword_sets(all_signals_text, sets, heading_text)
            chapter_candidates = [
                {"name": name, "score": round(score, 3), "source": "lexicon"}
                for name, score in ranked_chapters[:3]
            ]
            signals["chapter_keywords"] = chapter_candidates
            kw_chapter, kw_conf = _chapter_from_keywords(
                all_signals_text, course_name, heading_text
            )
            if kw_chapter:
                chapter_name, chapter_conf = kw_chapter, kw_conf
                chapter_source = "lexicon"
    if chapter_name:
        for ch in _existing_chapters(session_id, None):
            if ch["name"].lower() in all_signals_text.lower():
                chapter_name, chapter_conf = ch["name"], max(chapter_conf, 0.9)
                chapter_source = "existing"
                signals["existing_chapter_match"] = ch["name"]
                break
    if chapter_name and not chapter_candidates:
        chapter_candidates.append(
            {
                "name": chapter_name,
                "score": round(chapter_conf, 3),
                "source": chapter_source,
            }
        )

    # 7) knowledge points from content, with slide evidence
    kps = _kps_with_evidence(pages, course_name) if course_name else []
    signals["knowledge_points"] = [kp["name"] for kp in kps]

    # Combined confidence (documented formula):
    #   0.55 * course_signal + 0.30 * chapter_signal + 0.15 * retrieval_signal
    # The retrieval term only counts when it agrees with the chosen course.
    if course_name is None:
        confidence = 0.0
    else:
        chapter_part = chapter_conf if chapter_name else 0.0
        ret_part = min(ret_score, 1.0) if ret_course == course_name else 0.0
        confidence = (
            0.55 * min(course_confidence, 1.0) + 0.30 * chapter_part + 0.15 * ret_part
        )
    confidence = round(min(confidence, 1.0), 3)

    if reason in ("new_course", "ambiguous"):
        status = (
            "suggested" if (confidence >= mid_threshold and course_name) else "pending"
        )
    elif confidence >= high_threshold and course_name:
        status = "auto"
    elif confidence >= mid_threshold and course_name:
        status = "suggested"
    else:
        status = "pending"

    if reason == "ok" and course_name is None:
        reason = "new_course" if heading_course else "no_signal"

    # the chosen course must appear among the persisted candidates
    if course_name and not any(c["name"] == course_name for c in course_candidates):
        if signals.get("existing_course_match") == course_name:
            source = "existing"
        elif course_name == ret_course:
            source = "retrieval"
        else:
            source = "heading"
        course_candidates.append(
            {
                "name": course_name,
                "score": round(course_confidence, 3),
                "source": source,
            }
        )

    evidence = {
        "course": course_name,
        "course_confidence": round(course_confidence, 3),
        "chapter": chapter_name,
        "chapter_confidence": round(chapter_conf, 3),
        "knowledge_points": [kp["name"] for kp in kps],
        "kp_evidence": {kp["name"]: kp["slides"] for kp in kps},
        "course_candidates": course_candidates,
        "chapter_candidates": chapter_candidates,
        "status": status,
        "reason": reason,
        "classifier_version": CLASSIFIER_VERSION,
        "signals": signals,
        "formula": "0.55*course + 0.30*chapter + 0.15*retrieval",
    }
    return ClassifyDecision(
        course=course_name,
        chapter=chapter_name,
        knowledge_points=[kp["name"] for kp in kps],
        confidence=confidence,
        status=status,
        evidence=evidence,
        reason=reason,
        course_candidates=course_candidates,
        chapter_candidates=chapter_candidates,
        kp_evidence={kp["name"]: kp["slides"] for kp in kps},
    )
