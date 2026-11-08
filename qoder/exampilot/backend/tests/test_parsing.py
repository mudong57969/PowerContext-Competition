"""Unit tests for document parsing (MD/TXT; PDF/PPTX paths are exercised in integration)."""

import pytest

from app.services.parsing import (
    ParsedPage,
    ParseError,
    ParseResult,
    UnsupportedFileTypeError,
    parse_bytes,
)


class TestTextParsing:
    def test_txt_paragraphs_become_pages(self):
        result = parse_bytes("notes.txt", "第一段内容\n第二行\n\n第二段".encode())
        assert result.page_count == 2
        assert result.pages[0].text == "第一段内容\n第二行"
        assert result.pages[1].text == "第二段"

    def test_md_headings_split_sections(self):
        md = "# 数字集成电路\n正文内容\n\n## 第一章 MOS 器件\n阈值电压讲解".encode()
        result = parse_bytes("notes.md", md)
        assert result.page_count == 2
        assert result.pages[0].section == "数字集成电路"
        assert result.pages[1].section == "第一章 MOS 器件"

    def test_gb18030_fallback(self):
        result = parse_bytes("legacy.txt", "中文内容编码".encode("gb18030"))
        assert result.page_count == 1
        assert result.full_text == "中文内容编码"

    def test_unsupported_extension(self):
        with pytest.raises(UnsupportedFileTypeError):
            parse_bytes("slides.docx", b"whatever")

    def test_empty_file(self):
        result = parse_bytes("empty.txt", b"")
        assert result.page_count == 0

    def test_crlf_normalized(self):
        result = parse_bytes("win.txt", b"a\r\nb")
        assert result.pages[0].text == "a\nb"


class TestPdfFailurePath:
    def test_corrupt_pdf_raises_parse_error(self):
        with pytest.raises(ParseError):
            parse_bytes("broken.pdf", b"this is not a pdf")


def test_parse_result_properties():
    result = ParseResult(
        pages=[
            ParsedPage(page_number=1, text="hello"),
            ParsedPage(page_number=2, text="world"),
        ]
    )
    assert result.page_count == 2
    assert result.full_text == "hello\nworld"
    assert result.ocr_required is False
