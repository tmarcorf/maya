"""Curated pt-BR filler phrases for long-running Hermes turns (spec §15).

While the Hermes agent works (tool executions can take minutes), Polaris
speaks short fillers — a task-start acknowledgment ("Hmm, deixa eu ver"), a
tool narration ("vou mexer no terminal") and, when the stream stays silent
for too long, a continuation ("só mais um instante").

Pure logic here — no I/O — so the selection rules are unit-testable with
injected ``rng``/``clock``. The raw ``hermes.tool.progress`` payload is never
spoken: only the tool *name* selects a phrase pool, and every spoken string
is a curated phrase from the configured pools.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config.settings import Settings

DEFAULT_GENERIC_FILLERS: tuple[str, ...] = (
    "Hmm, deixa eu ver",
    "Blz, vou olhar",
    "Só um instante",
    "Vou verificar isso",
)

DEFAULT_SILENCE_FILLERS: tuple[str, ...] = (
    "só mais um instante",
    "ainda estou nisso",
    "já já te falo",
)

DEFAULT_TOOL_FILLERS: dict[str, str] = {
    "terminal": "vou mexer no terminal",
    "bash": "vou mexer no terminal",
    "browser": "vou abrir o navegador",
    "notion": "vou olhar no Notion",
    "memory": "vou buscar na memória",
    "skill": "vou usar uma skill",
    "subagent": "vou chamar um especialista",
    "file": "vou ler um arquivo",
}


class FillerController:
    """Per-turn filler state machine (selection, dedup and timing gates).

    Lifecycle: ``on_turn_start()`` resets the per-turn state when an LLM turn
    begins; ``on_turn_end()`` deactivates it (idempotent — both the ``[DONE]``
    branch and the ``finally`` of ``_process_context`` call it). Anti-chatter
    gates, all evaluated on the injected monotonic ``clock``:

    - at most one filler per ``toolCallId`` (a missing id degrades to one
      tool filler per turn);
    - ``min_interval`` between fillers and ``max_per_turn`` fillers per turn;
    - no phrase repeats back-to-back (``_pick`` excludes ``_last_phrase``);
    - every SSE chunk resets the silence clock (``note_activity``), and a
      spoken filler also resets it (it *is* the speech).
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        silence_timeout: float = 7.0,
        min_interval: float = 4.0,
        max_per_turn: int = 3,
        generic_phrases: Sequence[str] = DEFAULT_GENERIC_FILLERS,
        silence_phrases: Sequence[str] = DEFAULT_SILENCE_FILLERS,
        tool_phrases: Mapping[str, str] = DEFAULT_TOOL_FILLERS,
        rng: random.Random | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._enabled = enabled
        self._silence_timeout = silence_timeout
        self._min_interval = min_interval
        self._max_per_turn = max_per_turn
        self._generic_phrases = list(generic_phrases)
        self._silence_phrases = list(silence_phrases)
        self._tool_phrases = dict(tool_phrases)
        self._rng = rng or random.Random()
        self._clock = clock

        self._active = False
        self._seen_tool_call_ids: set[str] = set()
        self._last_phrase: str | None = None
        self._last_spoken_at: float | None = None
        self._spoken_count = 0
        self._last_activity = 0.0

    @classmethod
    def from_settings(cls, settings: Settings) -> FillerController:
        """Build a controller from the application Settings (FILLER_* knobs)."""
        return cls(
            enabled=settings.filler_enabled,
            silence_timeout=settings.filler_silence_timeout,
            min_interval=settings.filler_min_interval,
            max_per_turn=settings.filler_max_per_turn,
            generic_phrases=settings.filler_generic_phrases,
            silence_phrases=settings.filler_silence_phrases,
            tool_phrases=settings.filler_tool_phrases,
        )

    def is_enabled(self) -> bool:
        return self._enabled

    def on_turn_start(self) -> None:
        """Reset the per-turn state when an LLM turn begins."""
        self._active = True
        self._seen_tool_call_ids.clear()
        self._last_phrase = None
        self._last_spoken_at = None
        self._spoken_count = 0
        self.note_activity()

    def on_turn_end(self) -> None:
        """Deactivate (idempotent — called on [DONE] and in the finally)."""
        self._active = False

    def note_activity(self) -> None:
        """Any SSE chunk (text, tool progress, done) resets the silence clock.

        Keepalive comments never reach the chunk loop, so they do not reset
        it — connection-alive is not speech.
        """
        self._last_activity = self._clock()

    def seconds_until_silence_filler(self) -> float | None:
        """Seconds of remaining silence until a continuation filler is due.

        ``None`` when the turn is over or the controller is disabled; the
        watchdog sleeps this and asks again, so no timer arithmetic lives
        outside this class.
        """
        if not self._active or not self._enabled:
            return None
        return max(0.0, self._silence_timeout - (self._clock() - self._last_activity))

    def pick_tool_filler(self, tool_call_id: str, tool_name: str) -> str | None:
        """Phrase for a tool that started running, or ``None`` when gated.

        Dedup is recorded even when a gate blocks speech, so a given tool call
        is attempted at most once.
        """
        if not self._active or not self._enabled:
            return None
        if tool_call_id in self._seen_tool_call_ids:
            return None
        self._seen_tool_call_ids.add(tool_call_id)
        if not self._can_speak():
            return None
        known = self._tool_phrases.get(tool_name.lower())
        if known is not None:
            self._mark_spoken(known)
            return known
        return self._pick_and_mark(self._generic_phrases)

    def pick_silence_filler(self) -> str | None:
        """Continuation phrase after ``silence_timeout`` without activity."""
        if not self._active or not self._enabled:
            return None
        if not self._can_speak():
            return None
        if self._clock() - self._last_activity < self._silence_timeout:
            return None
        pool = self._silence_phrases or self._generic_phrases
        return self._pick_and_mark(pool)

    def _can_speak(self) -> bool:
        return not (
            self._spoken_count >= self._max_per_turn
            or (
                self._last_spoken_at is not None
                and self._clock() - self._last_spoken_at < self._min_interval
            )
        )

    def _pick_and_mark(self, pool: Sequence[str]) -> str | None:
        phrase = self._pick(pool)
        if phrase is None:
            return None
        self._mark_spoken(phrase)
        return phrase

    def _pick(self, pool: Sequence[str]) -> str | None:
        if not pool:
            return None
        # No consecutive repeats; a single-phrase pool may repeat.
        candidates = [phrase for phrase in pool if phrase != self._last_phrase]
        if not candidates:
            candidates = list(pool)
        return self._rng.choice(candidates)

    def _mark_spoken(self, phrase: str) -> None:
        now = self._clock()
        self._spoken_count += 1
        self._last_phrase = phrase
        self._last_spoken_at = now
        self._last_activity = now  # a filler is itself speech
