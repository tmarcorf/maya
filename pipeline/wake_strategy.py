"""Wake phrase strategy with a runtime on/off switch."""

from __future__ import annotations

from pipecat.frames.frames import Frame
from pipecat.turns.types import ProcessFrameResult
from pipecat.turns.user_start.wake_phrase_user_turn_start_strategy import (
    WakePhraseUserTurnStartStrategy,
)

from pipeline.wake_controller import WakeWordController


class ToggleableWakePhraseStrategy(WakePhraseUserTurnStartStrategy):
    """``WakePhraseUserTurnStartStrategy`` gated by a runtime flag.

    While the controller is disabled the strategy returns ``CONTINUE`` for
    every frame, so the remaining turn-start strategies behave exactly as
    if no wake word was configured. Enabling it delegates to the pipecat
    implementation (IDLE/AWAKE states untouched).

    Wake events are forwarded to the controller so the bridge can publish
    them; the controller is the single source of truth for the flag.
    """

    def __init__(self, *, controller: WakeWordController, **kwargs) -> None:
        super().__init__(**kwargs)
        self._controller = controller

        @self.event_handler("on_wake_phrase_detected")
        async def _on_wake_phrase_detected(_strategy, phrase):
            self._controller.notify_detected(phrase)

        @self.event_handler("on_wake_phrase_timeout")
        async def _on_wake_phrase_timeout(_strategy):
            self._controller.notify_timeout()

    async def process_frame(self, frame: Frame) -> ProcessFrameResult:
        if not self._controller.enabled:
            # Disabled mid-AWAKE: fall back asleep so re-enabling requires
            # the wake phrase again. Guarded by the current state (the
            # transition fires the timeout handler, which publishes the new
            # wake state to the bridge). Comparing the public state value
            # avoids importing the private pipecat enum.
            if self.state.value == "awake":
                self._transition_to_idle()
            return ProcessFrameResult.CONTINUE
        return await super().process_frame(frame)
