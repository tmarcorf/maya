"""Structured logging and latency metrics for the Maya voice agent.

Observability requirements come from spec §16: log lifecycle events (STT,
Hermes, TTS, interruption, errors) and emit latency metrics (STT latency,
time-to-first-token, time-to-first-audio, end-to-end latency).
"""

from __future__ import annotations

import sys
import time
from typing import Self

from loguru import logger

_LOG_FORMAT = (
    "<green>{time:HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>"
)


def setup_logging(level: str = "INFO") -> None:
    """Configure loguru to write to stderr at the given level."""
    logger.remove()
    logger.add(sys.stderr, level=level.upper(), format=_LOG_FORMAT)


def log_metric(name: str, value_ms: float, **tags: object) -> None:
    """Emit a single standardized latency metric line."""
    tag_str = " ".join(f"{key}={value}" for key, value in sorted(tags.items()))
    suffix = f" {tag_str}" if tag_str else ""
    logger.info(f"METRIC {name} value_ms={value_ms:.1f}{suffix}")


class LatencyTimer:
    """Context manager that logs elapsed time as a metric on exit."""

    def __init__(self, name: str, **tags: object) -> None:
        self._name = name
        self._tags = tags
        self._start: float | None = None

    def __enter__(self) -> Self:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc_info: object) -> bool:
        assert self._start is not None
        elapsed_ms = (time.perf_counter() - self._start) * 1000.0
        log_metric(self._name, elapsed_ms, **self._tags)
        return False
