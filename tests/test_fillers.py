"""Spec §15 — filler phrases during long Hermes turns.

Tool progress events are still never spoken verbatim, but with a
``FillerController`` attached the bridge speaks curated pt-BR fillers via
``TTSSpeakFrame(append_to_context=False)``, and a silence watchdog speaks a
continuation filler when the stream goes quiet for too long.
"""

from __future__ import annotations

import asyncio
import json
import random
from contextlib import suppress
from itertools import pairwise

import httpx
import respx
from conftest import HERMES_COMPLETIONS_URL, chunk, make_context, make_service, sse
from pipecat.frames.frames import (
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMServiceMetadataFrame,
    LLMTextFrame,
    TTSSpeakFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.frame_processor import FrameDirection
from pipecat.tests.utils import QueuedFrameProcessor, run_test
from pipecat.workers.runner import WorkerRunner

from pipeline.fillers import DEFAULT_SILENCE_FILLERS, FillerController


class _FakeClock:
    """Deterministic monotonic clock for FillerController tests."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _make_controller(clock: _FakeClock | None = None, **kwargs) -> FillerController:
    defaults: dict = {"rng": random.Random(1), "clock": clock or _FakeClock(), "min_interval": 1.0}
    defaults.update(kwargs)
    return FillerController(**defaults)


def _tool_payload(**overrides) -> str:
    payload = {
        "tool_name": "bash",
        "label": "ls -la /tmp",
        "emoji": "💻",
        "toolCallId": "call-1",
        "status": "running",
    }
    payload.update(overrides)
    return json.dumps(payload)


class _StallingSSEStream(httpx.AsyncByteStream):
    """Yields the given body once and then stalls — a long quiet tool turn."""

    def __init__(self, body: str, stall_secs: float = 60.0):
        self._body = body
        self._stall_secs = stall_secs

    async def __aiter__(self):
        yield self._body.encode()
        await asyncio.sleep(self._stall_secs)
        yield b""

    async def aclose(self):
        pass


# ---------------------------------------------------------------------------
# FillerController (unit — fake clock, no I/O)
# ---------------------------------------------------------------------------


def test_known_tool_picks_tool_specific_phrase():
    controller = _make_controller()
    controller.on_turn_start()
    assert controller.pick_tool_filler("call-1", "terminal") == "vou mexer no terminal"


def test_unknown_tool_falls_back_to_generic():
    controller = _make_controller(generic_phrases=["A", "B"], tool_phrases={})
    controller.on_turn_start()
    assert controller.pick_tool_filler("call-1", "weird-tool") in ("A", "B")


def test_picks_always_come_from_curated_pools():
    """The raw payload never becomes speech — only curated pool phrases."""
    clock = _FakeClock()
    controller = _make_controller(
        clock=clock,
        generic_phrases=["A", "B"],
        silence_phrases=["C", "D"],
        tool_phrases={"x": "X"},
    )
    controller.on_turn_start()
    assert controller.pick_tool_filler("call-1", "x") == "X"
    clock.advance(2)
    assert controller.pick_tool_filler("call-2", "unknown") in ("A", "B")
    clock.advance(controller._silence_timeout + 1)
    assert controller.pick_silence_filler() in ("C", "D")


def test_dedup_per_tool_call_id():
    clock = _FakeClock()
    controller = _make_controller(clock=clock)
    controller.on_turn_start()
    assert controller.pick_tool_filler("call-1", "bash") is not None
    clock.advance(2)
    assert controller.pick_tool_filler("call-1", "bash") is None
    # A different tool call may speak again.
    assert controller.pick_tool_filler("call-2", "bash") is not None


def test_min_interval_blocks_speaking():
    clock = _FakeClock()
    controller = _make_controller(clock=clock, min_interval=5.0)
    controller.on_turn_start()
    assert controller.pick_tool_filler("call-1", "bash") is not None
    clock.advance(2)
    # Dedup is recorded even when the interval gate blocks the speech.
    assert controller.pick_tool_filler("call-2", "bash") is None
    clock.advance(3)  # now >= min_interval since the last spoken filler
    assert controller.pick_tool_filler("call-3", "bash") is not None


def test_max_per_turn_caps_speaking():
    clock = _FakeClock()
    controller = _make_controller(clock=clock, max_per_turn=2)
    controller.on_turn_start()
    assert controller.pick_tool_filler("call-1", "bash") is not None
    clock.advance(2)
    assert controller.pick_tool_filler("call-2", "bash") is not None
    clock.advance(2)
    assert controller.pick_tool_filler("call-3", "bash") is None


def test_no_consecutive_repeat():
    clock = _FakeClock()
    controller = _make_controller(
        clock=clock, max_per_turn=10, generic_phrases=["A", "B"], tool_phrases={}
    )
    controller.on_turn_start()
    picks = []
    for i in range(4):
        clock.advance(2)
        phrase = controller.pick_tool_filler(f"call-{i}", "unknown")
        assert phrase is not None
        picks.append(phrase)
    for previous, current in pairwise(picks):
        assert current != previous


def test_single_phrase_pool_may_repeat():
    clock = _FakeClock()
    controller = _make_controller(clock=clock, generic_phrases=["A"], tool_phrases={})
    controller.on_turn_start()
    assert controller.pick_tool_filler("call-1", "unknown") == "A"
    clock.advance(2)
    assert controller.pick_tool_filler("call-2", "unknown") == "A"


def test_silence_filler_gates_on_timeout():
    clock = _FakeClock()
    controller = _make_controller(clock=clock, silence_timeout=7.0)
    controller.on_turn_start()
    assert controller.seconds_until_silence_filler() == 7.0
    clock.advance(3)
    assert controller.pick_silence_filler() is None
    assert controller.seconds_until_silence_filler() == 4.0
    clock.advance(4)
    assert controller.seconds_until_silence_filler() == 0.0
    assert controller.pick_silence_filler() is not None


def test_silence_filler_resets_clock():
    clock = _FakeClock()
    controller = _make_controller(clock=clock, silence_timeout=7.0)
    controller.on_turn_start()
    clock.advance(7)
    assert controller.pick_silence_filler() is not None
    # A spoken filler is itself speech: the silence clock restarted.
    assert controller.pick_silence_filler() is None
    assert controller.seconds_until_silence_filler() == 7.0


def test_turn_end_stops_picks():
    clock = _FakeClock()
    controller = _make_controller(clock=clock)
    controller.on_turn_start()
    controller.on_turn_end()
    assert controller.pick_tool_filler("call-1", "bash") is None
    assert controller.pick_silence_filler() is None
    assert controller.seconds_until_silence_filler() is None
    # A new turn resets the per-turn state.
    controller.on_turn_start()
    assert controller.pick_tool_filler("call-1", "bash") is not None


def test_disabled_controller_speaks_nothing():
    clock = _FakeClock()
    controller = _make_controller(clock=clock, enabled=False)
    controller.on_turn_start()
    assert not controller.is_enabled()
    assert controller.pick_tool_filler("call-1", "bash") is None
    clock.advance(10)
    assert controller.pick_silence_filler() is None
    assert controller.seconds_until_silence_filler() is None


# ---------------------------------------------------------------------------
# HermesLLMService (respx — tool progress → TTSSpeakFrame)
# ---------------------------------------------------------------------------


@respx.mock
async def test_tool_progress_running_speaks_curated_filler():
    respx.post(HERMES_COMPLETIONS_URL).mock(
        return_value=respx.MockResponse(
            200,
            content=sse(
                (None, chunk("Vou")),
                ("hermes.tool.progress", _tool_payload()),
                (None, chunk(" verificar")),
                (None, "[DONE]"),
            ),
        )
    )
    service = make_service(filler=FillerController(rng=random.Random(1), min_interval=0.0))

    down, _up = await run_test(
        service,
        frames_to_send=[LLMContextFrame(context=make_context())],
        expected_down_frames=[
            LLMServiceMetadataFrame,
            LLMFullResponseStartFrame,
            LLMTextFrame,
            TTSSpeakFrame,
            LLMTextFrame,
            LLMFullResponseEndFrame,
        ],
        expected_up_frames=[LLMServiceMetadataFrame],
    )

    speaks = [frame for frame in down if isinstance(frame, TTSSpeakFrame)]
    assert len(speaks) == 1
    # The raw payload is never spoken — a curated phrase for the tool name.
    assert speaks[0].text == "vou mexer no terminal"
    assert speaks[0].append_to_context is False
    assert "ls" not in speaks[0].text


@respx.mock
async def test_tool_progress_completed_does_not_speak():
    respx.post(HERMES_COMPLETIONS_URL).mock(
        return_value=respx.MockResponse(
            200,
            content=sse(
                ("hermes.tool.progress", _tool_payload(status="completed")),
                (None, "[DONE]"),
            ),
        )
    )
    service = make_service(filler=FillerController(rng=random.Random(1)))

    down, _up = await run_test(
        service,
        frames_to_send=[LLMContextFrame(context=make_context())],
        expected_down_frames=[
            LLMServiceMetadataFrame,
            LLMFullResponseStartFrame,
            LLMFullResponseEndFrame,
        ],
        expected_up_frames=[LLMServiceMetadataFrame],
    )

    assert not [frame for frame in down if isinstance(frame, TTSSpeakFrame)]


@respx.mock
async def test_no_filler_without_controller():
    """Regression (§15): without a controller, tool progress stays filtered."""
    respx.post(HERMES_COMPLETIONS_URL).mock(
        return_value=respx.MockResponse(
            200,
            content=sse(
                (None, chunk("Vou")),
                ("hermes.tool.progress", _tool_payload()),
                (None, chunk(" verificar")),
                (None, "[DONE]"),
            ),
        )
    )
    service = make_service()

    down, _up = await run_test(
        service,
        frames_to_send=[LLMContextFrame(context=make_context())],
        expected_down_frames=[
            LLMServiceMetadataFrame,
            LLMFullResponseStartFrame,
            LLMTextFrame,
            LLMTextFrame,
            LLMFullResponseEndFrame,
        ],
        expected_up_frames=[LLMServiceMetadataFrame],
    )

    assert not [frame for frame in down if isinstance(frame, TTSSpeakFrame)]


# ---------------------------------------------------------------------------
# Silence watchdog (manual pipeline — stalling stream)
# ---------------------------------------------------------------------------


@respx.mock
async def test_silence_watchdog_speaks_continuation_filler():
    respx.post(HERMES_COMPLETIONS_URL).mock(
        return_value=respx.MockResponse(200, stream=_StallingSSEStream("")),
    )
    service = make_service(
        filler=FillerController(
            silence_timeout=0.2, min_interval=0.05, rng=random.Random(1)
        )
    )

    received_down: asyncio.Queue = asyncio.Queue()
    source = QueuedFrameProcessor(
        queue=asyncio.Queue(),
        queue_direction=FrameDirection.UPSTREAM,
        ignore_start=True,
    )
    sink = QueuedFrameProcessor(
        queue=received_down,
        queue_direction=FrameDirection.DOWNSTREAM,
        ignore_start=True,
    )

    pipeline = Pipeline([source, service, sink])
    worker = PipelineWorker(pipeline, cancel_on_idle_timeout=False, params=PipelineParams())
    runner = WorkerRunner()
    await runner.add_workers(worker)
    run_task = asyncio.create_task(runner.run())

    try:
        await asyncio.sleep(0.05)  # let the pipeline start
        await worker.queue_frame(LLMContextFrame(context=make_context()))

        # No chunks arrive (empty body + stall) — only the watchdog speaks.
        speak = None
        while not isinstance(speak, TTSSpeakFrame):
            frame = await asyncio.wait_for(received_down.get(), timeout=10)
            if isinstance(frame, TTSSpeakFrame):
                speak = frame
        assert speak.text in DEFAULT_SILENCE_FILLERS
        assert speak.append_to_context is False
    finally:
        await runner.cancel()
        with suppress(asyncio.CancelledError):
            await run_task


@respx.mock
async def test_watchdog_cancelled_on_interruption():
    respx.post(HERMES_COMPLETIONS_URL).mock(
        return_value=respx.MockResponse(
            200,
            stream=_StallingSSEStream(
                sse(("hermes.tool.progress", _tool_payload())), stall_secs=60.0
            ),
        )
    )
    service = make_service(
        filler=FillerController(
            silence_timeout=0.6, min_interval=0.05, rng=random.Random(1)
        )
    )

    received_down: asyncio.Queue = asyncio.Queue()
    source = QueuedFrameProcessor(
        queue=asyncio.Queue(),
        queue_direction=FrameDirection.UPSTREAM,
        ignore_start=True,
    )
    sink = QueuedFrameProcessor(
        queue=received_down,
        queue_direction=FrameDirection.DOWNSTREAM,
        ignore_start=True,
    )

    pipeline = Pipeline([source, service, sink])
    worker = PipelineWorker(pipeline, cancel_on_idle_timeout=False, params=PipelineParams())
    runner = WorkerRunner()
    await runner.add_workers(worker)
    run_task = asyncio.create_task(runner.run())

    try:
        await asyncio.sleep(0.05)  # let the pipeline start
        await worker.queue_frame(LLMContextFrame(context=make_context()))

        # The tool filler speaks immediately...
        first = await asyncio.wait_for(received_down.get(), timeout=10)
        while not isinstance(first, TTSSpeakFrame):
            first = await asyncio.wait_for(received_down.get(), timeout=10)
        assert first.text == "vou mexer no terminal"

        # ...then the user barges in mid-stall.
        await source.queue_frame(InterruptionFrame())

        end = await asyncio.wait_for(received_down.get(), timeout=10)
        while not isinstance(end, LLMFullResponseEndFrame):
            end = await asyncio.wait_for(received_down.get(), timeout=10)

        # The watchdog died with the turn: no filler within a window longer
        # than the 0.6 s silence timeout it would have fired on.
        try:
            while True:
                frame = await asyncio.wait_for(received_down.get(), timeout=1.2)
                assert not isinstance(frame, TTSSpeakFrame), (
                    "filler leaked after interruption"
                )
        except TimeoutError:
            pass
    finally:
        await runner.cancel()
        with suppress(asyncio.CancelledError):
            await run_task
