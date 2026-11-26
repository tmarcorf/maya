from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    return text[:max_chars].rstrip()


def normalize_url(value: str) -> str | None:
    url = clean_text(value)
    if not url:
        return None

    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return url
