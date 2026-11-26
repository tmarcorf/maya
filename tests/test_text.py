from __future__ import annotations

from maya_agent.tools.text import clean_text, normalize_url, truncate


def test_clean_text_collapses_whitespace() -> None:
    assert clean_text("  olá\n mundo\t ") == "olá mundo"
    assert clean_text(None) == ""
    assert clean_text(123) == "123"


def test_truncate_limits_and_strips_trailing_space() -> None:
    assert truncate("abcdef", 3) == "abc"
    assert truncate("abc   ", 3) == "abc"
    assert truncate("abc", 0) == ""
    assert truncate("abc", 10) == "abc"


def test_normalize_url_accepts_http_and_https() -> None:
    assert normalize_url(" https://example.com/page ") == "https://example.com/page"
    assert normalize_url("http://example.com") == "http://example.com"


def test_normalize_url_rejects_invalid_urls() -> None:
    assert normalize_url("") is None
    assert normalize_url("example.com") is None
    assert normalize_url("ftp://example.com") is None
    assert normalize_url("https:///missing-host") is None
