"""Runtime on/off switch for the wake word gating (desktop bridge support)."""

from __future__ import annotations

from collections.abc import Callable


class WakeWordController:
    """Mutable wake-word flag shared by the strategy and the bridge.

    ``Settings`` is frozen, so ``WAKE_WORD_ENABLED`` only sets the initial
    state at startup; the desktop app toggles the flag at runtime through
    the bridge. Session-only by design — the next start reads the env again.

    Also tracks the wake state (asleep/awake) reported by the strategy so
    the bridge can publish it without reaching into pipecat internals.
    """

    def __init__(self, enabled: bool = False) -> None:
        self._enabled = enabled
        self._state = "asleep"
        self._phrase: str | None = None
        self._on_event: Callable[[str, dict], None] | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def state(self) -> str:
        """Current wake state: ``"asleep"``, ``"awake"`` or ``"disabled"``."""
        if not self._enabled:
            return "disabled"
        return self._state

    @property
    def phrase(self) -> str | None:
        """The last matched wake phrase, if any."""
        return self._phrase

    def set_listener(self, on_event: Callable[[str, dict], None] | None) -> None:
        """Register the callback receiving ``(event, data)`` notifications."""
        self._on_event = on_event

    def set_enabled(self, enabled: bool) -> bool:
        """Toggle the flag; emits ``enabled_changed`` when the value moves."""
        if self._enabled == enabled:
            return self._enabled
        self._enabled = enabled
        self._state = "asleep"
        self._phrase = None
        self._emit("enabled_changed", {"enabled": enabled})
        return self._enabled

    def notify_detected(self, phrase: str) -> None:
        """Record a wake phrase match (ignored while disabled)."""
        if not self._enabled:
            return
        self._state = "awake"
        self._phrase = phrase
        self._emit("detected", {"phrase": phrase})

    def notify_timeout(self) -> None:
        """Record the wake timeout (ignored while disabled)."""
        if not self._enabled:
            return
        self._state = "asleep"
        self._phrase = None
        self._emit("timeout", {})

    def _emit(self, event: str, data: dict) -> None:
        if self._on_event is not None:
            self._on_event(event, data)
