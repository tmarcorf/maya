"""Runtime wake-word toggle: controller + toggleable strategy."""

from __future__ import annotations

import asyncio

from pipecat.frames.frames import TranscriptionFrame
from pipecat.turns.types import ProcessFrameResult

from pipeline.wake_controller import WakeWordController
from pipeline.wake_strategy import ToggleableWakePhraseStrategy


def _transcription(text: str) -> TranscriptionFrame:
    """A final transcription like the STT service emits."""
    return TranscriptionFrame(text=text, user_id="user", timestamp="2026-08-19T12:00:00Z")


class _StubTaskManager:
    """Schedule event-handler coroutines on the running loop.

    The wake strategy dispatches ``on_wake_phrase_detected``/``timeout``
    through the task manager; scheduling for real lets those handlers run
    (tests use ``_wait_for`` to drain the nested tasks).
    """

    def create_task(self, coro, _name=None):
        return asyncio.create_task(coro)


async def _wait_for(predicate, tries: int = 10) -> bool:
    """Yield until ``predicate`` is true (event handlers dispatch via
    nested tasks, so a single ``sleep(0)`` is not enough)."""
    for _ in range(tries):
        if predicate():
            return True
        await asyncio.sleep(0)
    return False


def _make_strategy(enabled: bool = True) -> tuple[WakeWordController, ToggleableWakePhraseStrategy]:
    controller = WakeWordController(enabled=enabled)
    strategy = ToggleableWakePhraseStrategy(
        controller=controller,
        phrases=["e aí polaris"],
        timeout=10,
    )
    return controller, strategy


def test_controller_starts_disabled_and_reports_state():
    controller = WakeWordController(enabled=False)
    assert controller.enabled is False
    assert controller.state == "disabled"


def test_controller_toggle_emits_event_once():
    events = []
    controller = WakeWordController(enabled=False)
    controller.set_listener(lambda event, data: events.append((event, data)))

    controller.set_enabled(True)

    assert controller.enabled is True
    assert controller.state == "asleep"
    assert events == [("enabled_changed", {"enabled": True})]

    # Same value: no event, no state churn.
    controller.set_enabled(True)
    assert events == [("enabled_changed", {"enabled": True})]


def test_controller_tracks_detected_and_timeout():
    controller = WakeWordController(enabled=True)

    controller.notify_detected("e aí polaris")
    assert controller.state == "awake"
    assert controller.phrase == "e aí polaris"

    controller.notify_timeout()
    assert controller.state == "asleep"
    assert controller.phrase is None


def test_controller_ignores_strategy_events_while_disabled():
    controller = WakeWordController(enabled=False)

    controller.notify_detected("e aí polaris")
    controller.notify_timeout()

    assert controller.state == "disabled"
    assert controller.phrase is None


async def test_disabled_strategy_passes_everything_through():
    _controller, strategy = _make_strategy(enabled=False)

    result = await strategy.process_frame(_transcription("que horas são?"))

    assert result is ProcessFrameResult.CONTINUE
    assert strategy.state.value == "idle"


async def test_enabled_strategy_blocks_until_wake_phrase():
    controller, strategy = _make_strategy(enabled=True)
    strategy._task_manager = _StubTaskManager()

    # Unrelated speech is blocked (STOP).
    assert (
        await strategy.process_frame(_transcription("que horas são?"))
        is ProcessFrameResult.STOP
    )
    # The wake phrase matches (STOP: the turn-start controller takes over)
    # and the match is forwarded to the controller.
    assert (
        await strategy.process_frame(_transcription("E aí, Polaris"))
        is ProcessFrameResult.STOP
    )
    assert await _wait_for(lambda: controller.state == "awake")
    assert controller.phrase == "e aí polaris"

    # Awake: frames continue to the remaining strategies.
    assert (
        await strategy.process_frame(_transcription("que horas são?"))
        is ProcessFrameResult.CONTINUE
    )


async def test_disabling_mid_awake_returns_to_sleep():
    controller, strategy = _make_strategy(enabled=True)
    strategy._task_manager = _StubTaskManager()
    await strategy.process_frame(_transcription("E aí, Polaris"))
    assert strategy.state.value == "awake"

    controller.set_enabled(False)

    result = await strategy.process_frame(_transcription("qualquer coisa"))
    assert result is ProcessFrameResult.CONTINUE
    # The lazy reset happened: re-enabling will require the wake phrase.
    assert strategy.state.value == "idle"
    assert controller.state == "disabled"
