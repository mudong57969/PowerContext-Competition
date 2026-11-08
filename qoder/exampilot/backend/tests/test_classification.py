"""Unit tests for deterministic course/chapter/KP classification."""

import json
from pathlib import Path

from app.services.classification import (
    _chapter_from_patterns,
    _keyword_score,
    _kps_from_keywords,
    classify_document,
)
from app.services.parsing import ParsedPage, ParseResult

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _make_parse(text: str) -> ParseResult:
    return ParseResult(pages=[ParsedPage(page_number=1, text=text)])


def _make_pages(*pages: tuple[int, str, str | None]) -> ParseResult:
    return ParseResult(
        pages=[ParsedPage(page_number=n, text=t, section=s) for n, t, s in pages]
    )


def _load_fixture(name: str) -> list[dict]:
    with open(FIXTURE_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def _isolated(monkeypatch):
    monkeypatch.setattr("app.services.classification._existing_courses", lambda sid: [])
    monkeypatch.setattr(
        "app.services.classification._retrieval_signal", lambda sid, text: (None, 0.0)
    )
    monkeypatch.setattr(
        "app.services.classification._existing_chapters", lambda sid, cid: []
    )


class TestKeywordScore:
    def test_substring_hits(self):
        assert _keyword_score("动态功耗 泄漏功耗", ["功耗"]) > 0.4

    def test_partial_and_zero(self):
        assert 0 < _keyword_score("cmos", ["cmos", "vlsi", "反相器"]) < 0.6
        assert _keyword_score("模拟", ["cmos"]) == 0.0

    def test_empty_keywords(self):
        assert _keyword_score("anything", []) == 0.0


class TestChapterPatterns:
    def test_chinese_chapter(self):
        name, conf = _chapter_from_patterns("第一章 MOS 器件")
        assert name == "MOS 器件" and conf == 0.9

    def test_english_chapter(self):
        name, conf = _chapter_from_patterns("Chapter 2: CMOS Inverter")
        assert name == "CMOS Inverter" and conf == 0.9

    def test_no_pattern(self):
        assert _chapter_from_patterns("普通正文") == (None, 0.0)


class TestKnowledgePoints:
    def test_kps_need_enough_keyword_hits(self):
        assert _kps_from_keywords("阈值电压 threshold voltage", "数字集成电路") == [
            "MOS 阈值电压"
        ]
        assert _kps_from_keywords("动态功耗 p = α", "数字集成电路") == ["动态功耗"]


class TestClassifyDocument:
    def test_auto_classification(self, monkeypatch):
        _isolated(monkeypatch)
        text = (
            "# 数字集成电路\n## 第一章 MOS 器件\n"
            "cmos vlsi 反相器 inverter mos 阈值电压 功耗 传播延迟 互连 噪声容限"
        )
        decision = classify_document(
            "s1", "cmos_notes.md", _make_parse(text), 0.65, 0.45
        )
        assert decision.course == "数字集成电路"
        assert decision.chapter == "MOS 器件"
        assert decision.status == "auto"
        assert decision.confidence >= 0.65

    def test_suggested_band(self, monkeypatch):
        _isolated(monkeypatch)
        text = "## 第一章 CMOS 反相器\ncmos 反相器 阈值电压\n本文介绍上述基本概念，供课后复习使用，请结合教材学习。"
        decision = classify_document("s1", "notes.md", _make_parse(text), 0.65, 0.45)
        assert decision.course == "数字集成电路"
        assert decision.status == "suggested"
        assert 0.45 <= decision.confidence < 0.65

    def test_pending_without_signals(self, monkeypatch):
        _isolated(monkeypatch)
        decision = classify_document(
            "s1", "mystery.md", _make_parse("今天天气不错"), 0.65, 0.45
        )
        assert decision.course is None
        assert decision.status == "pending"
        assert decision.confidence == 0.0

    def test_knowledge_points_extracted(self, monkeypatch):
        _isolated(monkeypatch)
        text = "# 数字集成电路\n第一章 MOS 器件\n阈值电压 threshold voltage 动态功耗 p = α cmos"
        decision = classify_document(
            "s1", "cmos_notes.md", _make_parse(text), 0.65, 0.45
        )
        assert "MOS 阈值电压" in decision.knowledge_points
        assert "动态功耗" in decision.knowledge_points


class TestRealMosDeck:
    """Scenario 1: the real extracted text of 03-chapter2-device02-MOS-dynamic_T.pptx."""

    def test_real_deck_classifies_with_multi_kp_evidence(self, monkeypatch):
        _isolated(monkeypatch)
        pages = [
            ParsedPage(page_number=p["page_number"], text=p["text"])
            for p in _load_fixture("mos_deck_pages.json")
        ]
        decision = classify_document(
            "s1",
            "03-chapter2-device02-MOS-dynamic_T.pptx",
            ParseResult(pages=pages),
            0.65,
            0.45,
        )
        assert decision.course == "数字集成电路"
        assert decision.chapter == "MOS 器件"
        assert decision.status == "auto"
        assert decision.confidence >= 0.65
        assert decision.reason == "ok"
        # the deck covers several knowledge points, each evidenced by slides
        assert len(decision.knowledge_points) >= 3
        for name in ("MOS 阈值电压", "体效应", "速度饱和"):
            assert name in decision.knowledge_points
        assert decision.kp_evidence
        for name, slides in decision.kp_evidence.items():
            assert name in decision.knowledge_points
            assert slides and all(1 <= s <= len(pages) for s in slides)
        assert 8 in decision.kp_evidence.get("体效应", [])  # slide titled "Body effect"


class TestNewCourse:
    """Scenario 2: a course never seen before (not in the lexicon)."""

    def test_heading_proposes_new_course(self, monkeypatch):
        _isolated(monkeypatch)
        parse = _make_pages(
            (1, "Quantum Computing\nAn introduction to qubits", "Quantum Computing"),
            (
                2,
                "Chapter 1 Qubits\nsuperposition and entanglement of qubits",
                "Chapter 1 Qubits",
            ),
            (
                3,
                "Chapter 2 Quantum Gates\nhadamard and cnot gates",
                "Chapter 2 Quantum Gates",
            ),
        )
        decision = classify_document("s1", "lecture1.pdf", parse, 0.65, 0.45)
        assert decision.course == "Quantum Computing"
        assert decision.reason == "new_course"
        assert decision.status in ("suggested", "pending")
        assert decision.chapter == "Qubits"
        assert any(c["source"] == "heading" for c in decision.course_candidates)


class TestEnglishMaterial:
    """Scenario 3: an all-English deck is mapped to the Chinese course lexicon."""

    def test_english_deck_classifies(self, monkeypatch):
        _isolated(monkeypatch)
        text = (
            "# Digital Integrated Circuits\n"
            "## Chapter 2 MOS Devices\n"
            "VLSI CMOS digital integrated circuit design covers the MOS transistor, "
            "inverter, threshold voltage, power, propagation delay and noise margin.\n"
            "Threshold voltage, threshold variation and threshold shift (DIBL) set vth.\n"
            "Body effect changes the threshold voltage with source bulk bias.\n"
            "Velocity saturation limits carrier velocity in short-channel effect transistors."
        )
        decision = classify_document(
            "s1", "lecture2_english.pdf", _make_parse(text), 0.65, 0.45
        )
        assert decision.course == "数字集成电路"
        assert decision.chapter == "MOS Devices"
        assert decision.status == "auto"
        for name in ("MOS 阈值电压", "体效应", "速度饱和", "短沟道效应"):
            assert name in decision.knowledge_points
        assert decision.kp_evidence.get("MOS 阈值电压") == [1]


class TestMixedLanguage:
    """Scenario 4: mixed Chinese/English material with chapter pattern and KPs."""

    def test_mixed_language_classifies(self, monkeypatch):
        _isolated(monkeypatch)
        text = (
            "# 数字集成电路\n"
            "第一章 MOS 器件\n"
            "阈值电压 threshold voltage 体效应 body effect 沟道长度调制 channel length modulation\n"
            "cmos 反相器 功耗 传播延迟 互连 噪声容限"
        )
        decision = classify_document(
            "s1", "notes_mixed.md", _make_parse(text), 0.65, 0.45
        )
        assert decision.course == "数字集成电路"
        assert decision.chapter == "MOS 器件"
        assert decision.status == "auto"
        for name in ("MOS 阈值电压", "体效应", "沟道长度调制"):
            assert name in decision.knowledge_points
            assert decision.kp_evidence.get(name) == [1]


class TestFilenameBodyConflict:
    """Scenario 5: filename hints at one course, content decides another."""

    def test_content_beats_filename(self, monkeypatch):
        _isolated(monkeypatch)
        text = (
            "# 数字集成电路\n## 第一章 MOS 器件\n"
            "cmos vlsi 反相器 inverter mos 阈值电压 功耗 传播延迟 互连 噪声容限"
        )
        decision = classify_document(
            "s1", "probability_notes.pdf", _make_parse(text), 0.65, 0.45
        )
        assert decision.course == "数字集成电路"
        assert decision.course != "概率论"
        assert decision.status == "auto"
        assert all(c["source"] == "lexicon" for c in decision.course_candidates)


class TestUnparseablePptx:
    """Scenario 6: a PPTX with no extractable text, and parsed-but-unclassifiable text."""

    def test_insufficient_text_reason_and_filename_candidates(self, monkeypatch):
        _isolated(monkeypatch)
        parse = ParseResult(pages=[ParsedPage(page_number=1, text="   ")])
        decision = classify_document("s1", "lab02_mos_notes.pptx", parse, 0.65, 0.45)
        assert decision.reason == "insufficient_text"
        assert decision.course is None
        assert decision.status == "pending"
        assert decision.confidence == 0.0
        assert decision.course_candidates
        assert all(c["source"] == "filename" for c in decision.course_candidates)

    def test_parsed_but_unclassifiable_is_no_signal(self, monkeypatch):
        _isolated(monkeypatch)
        text = "今天天气不错，我们去公园散步，顺便买了一些水果和蔬菜回家做饭，晚上还看了场电影，感觉很开心。日子过得真快啊。"
        decision = classify_document("s1", "mystery.md", _make_parse(text), 0.65, 0.45)
        assert decision.reason == "no_signal"
        assert decision.course is None
        assert decision.status == "pending"
        assert decision.course_candidates == []


class TestMultiChapterMultiKp:
    """Scenario 7: one document spanning chapters, multiple KPs, per-slide evidence."""

    def test_multi_chapter_multi_kp_with_slide_evidence(self, monkeypatch):
        _isolated(monkeypatch)
        parse = _make_pages(
            (
                1,
                (
                    "第一章 MOS 器件\n"
                    "阈值电压 threshold voltage 体效应 body effect cmos 反相器 功耗 传播延迟 互连"
                ),
                "第一章 MOS 器件",
            ),
            (
                2,
                (
                    "第二章 功耗\n"
                    "动态功耗 dynamic power p=α 泄漏功耗 leakage power 功耗 传播延迟"
                ),
                "第二章 功耗",
            ),
        )
        decision = classify_document("s1", "chapter1_2.pdf", parse, 0.65, 0.45)
        assert decision.course == "数字集成电路"
        assert decision.chapter == "MOS 器件"  # first chapter pattern wins
        assert len(decision.knowledge_points) >= 2
        assert decision.kp_evidence.get("体效应") == [1]
        assert decision.kp_evidence.get("动态功耗") == [2]


class TestLowConfidence:
    """Scenario 8: weak signals stay pending but show candidates instead of blanks."""

    def test_low_confidence_shows_candidates(self, monkeypatch):
        _isolated(monkeypatch)
        text = "# 电路基础\n反相器 功耗\n本文介绍电路的基本概念，后续章节将展开详细讨论。重点是掌握基本元件的特性。"
        decision = classify_document("s1", "basics.md", _make_parse(text), 0.65, 0.45)
        assert decision.status == "pending"
        assert decision.confidence < 0.45
        assert decision.course == "数字集成电路"  # weakly supported by content
        assert decision.course_candidates
        assert decision.course_candidates[0]["name"] == "数字集成电路"
        assert decision.course_candidates[0]["score"] < 0.45


class TestAmbiguity:
    """Top course candidates too close to call -> ambiguous reason."""

    def test_ambiguous_candidates(self, monkeypatch):
        _isolated(monkeypatch)

        def _fake_rank(text, sets, title_text=""):
            if set(sets) & {"MOS 器件", "CMOS 反相器", "功耗", "互连线", "工艺与缩放"}:
                return [("MOS 器件", 0.7), ("功耗", 0.5)]
            return [("数字集成电路", 0.50), ("模拟集成电路", 0.44)]

        monkeypatch.setattr(
            "app.services.classification._rank_keyword_sets", _fake_rank
        )
        text = "cmos 反相器 运算放大器 opamp 阈值电压\n本讲义覆盖放大电路与数字逻辑的基本单元，供复习参考。"
        decision = classify_document("s1", "notes.md", _make_parse(text), 0.65, 0.45)
        assert decision.reason == "ambiguous"
        assert decision.course == "数字集成电路"
        assert decision.status in ("suggested", "pending")
        assert len(decision.course_candidates) >= 2


class TestProbabilityCourse:
    """Scenario: 概率论 material (in the lexicon) auto-classifies; generic KPs
    are never fabricated for courses without curated keyword sets."""

    def test_probability_classifies(self, monkeypatch):
        _isolated(monkeypatch)
        text = (
            "# 概率论与数理统计\n"
            "## 第一章 随机事件与概率\n"
            "概率论 probability 随机变量 random variable 分布 distribution\n"
            "## 第二章 随机变量及其分布\n"
            "正态分布 density 期望 expectation 方差 variance 泊松分布"
        )
        decision = classify_document(
            "s1", "probability_notes.md", _make_parse(text), 0.65, 0.45
        )
        assert decision.course == "概率论"
        assert decision.status == "auto"
        assert any(c["source"] == "lexicon" for c in decision.course_candidates)

    def test_probability_no_fabricated_kps(self, monkeypatch):
        _isolated(monkeypatch)
        text = (
            "# 概率论与数理统计\n## 第一章 随机事件与概率\n"
            "概率论 probability 随机变量 random variable 分布 distribution"
        )
        decision = classify_document(
            "s1", "probability_notes.md", _make_parse(text), 0.65, 0.45
        )
        # 概率论 has no curated KP lexicon; chapter-pattern headings are not
        # knowledge points, so nothing is fabricated.
        for kp in decision.knowledge_points:
            assert "第一章" not in kp and "概率论" not in kp, kp


class TestDataStructuresNewCourse:
    """Scenario: 数据结构 is not in the lexicon — a structured heading must
    propose it as a new course instead of any weak match."""

    def test_heading_proposes_new_course(self, monkeypatch):
        _isolated(monkeypatch)
        parse = _make_pages(
            (1, "# 数据结构与算法", "数据结构与算法"),
            (2, "## 第一章 线性表\n线性表是 n 个数据元素的有限序列。", "第一章 线性表"),
            (3, "## 第二章 树\n二叉树每个节点至多两个子树。", "第二章 树"),
        )
        decision = classify_document("s1", "ds_notes.md", parse, 0.65, 0.45)
        assert decision.course == "数据结构与算法"
        assert decision.reason == "new_course"
        assert any(c["source"] == "heading" for c in decision.course_candidates)


class TestGenericKpsWithEvidence:
    """Scenario: cross-course KPs come from term-like headings with real page
    evidence, not from the digital-IC lexicon."""

    def test_term_heading_kps_have_page_evidence(self, monkeypatch):
        _isolated(monkeypatch)
        parse = _make_pages(
            (1, "# 数据结构与算法", "数据结构与算法"),
            (2, "## 第一章 线性表\n线性表是 n 个数据元素的有限序列。", "第一章 线性表"),
            (3, "### 链表\n链表通过指针链接节点，链表插入删除只需修改指针。", "链表"),
            (
                4,
                "### 栈与队列\n栈是后进先出的线性表，可以用链表实现栈与队列。",
                "栈与队列",
            ),
            (
                5,
                "## 第二章 树\n二叉树每个节点至多两个子树。链表与栈与队列都是线性结构。",
                "第二章 树",
            ),
        )
        decision = classify_document("s1", "ds_kp.md", parse, 0.65, 0.45)
        assert decision.course == "数据结构与算法"
        assert decision.reason == "new_course"
        assert "链表" in decision.knowledge_points
        assert "栈与队列" in decision.knowledge_points
        # chapter-pattern headings must not leak in as KPs
        for kp in decision.knowledge_points:
            assert "第一章" not in kp and "第二章" not in kp
        # every KP must carry real page evidence
        assert decision.kp_evidence
        for name, slides in decision.kp_evidence.items():
            assert name in decision.knowledge_points
            assert len(slides) >= 2, name
            assert all(1 <= s <= len(parse.pages) for s in slides)
        assert 3 in decision.kp_evidence["链表"]
        assert 4 in decision.kp_evidence["栈与队列"]


class TestExistingCourseMentionDoesNotOverride:
    """Scenario: a mere mention of an existing course name must not override
    a different, structurally evidenced course title."""

    def test_mention_of_existing_course_loses_to_heading(self, monkeypatch):

        monkeypatch.setattr(
            "app.services.classification._existing_courses",
            lambda sid: [{"id": 1, "name": "数字集成电路"}],
        )
        monkeypatch.setattr(
            "app.services.classification._retrieval_signal",
            lambda sid, text: (None, 0.0),
        )
        monkeypatch.setattr(
            "app.services.classification._existing_chapters", lambda sid, cid: []
        )
        text = (
            "# 数据结构与算法\n## 第一章 线性表\n"
            "线性表是 n 个数据元素的有限序列，链表通过指针链接节点。\n"
            "本课程实验平台与数字集成电路实验共用机房。"
        )
        decision = classify_document("s1", "ds_notes.md", _make_parse(text), 0.65, 0.45)
        assert decision.course == "数据结构与算法"
        assert decision.reason == "new_course"
        assert "existing_course_mention_only" in decision.evidence["signals"]
