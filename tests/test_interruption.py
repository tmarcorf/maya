"""Spec §19 item 8 — interruption/cancellation of an in-flight Hermes turn.

Simulates barge-in: while the Hermes stream is still producing, an
InterruptionFrame arrives (as the VAD controller would broadcast it), the
pipeline cancels the in-flight completion and the turn is still closed with
LLMFullResponseEndFrame (§9).
"""

from __future__ import annotations

import asyncio
from contextlib import suppress

import httpx
import respx
from conftest import HERMES_COMPLETIONS_URL, chunk, make_context, make_service, sse
from pipecat.frames.frames import (
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMTextFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.frame_processor import FrameDirection
from pipecat.tests.utils import QueuedFrameProcessor
from pipecat.workers.runner import WorkerRunner


class _StallingSSEStream(httpx.AsyncByteStream):
    """Yields one chunk and then stalls — like a long-running tool turn."""

    def __init__(self, body: str, stall_secs: float = 60.0):
        self._body = body
        self._stall_secs = stall_secs

    async def __aiter__(self):
        yield self._body.encode()
        await asyncio.sleep(self._stall_secs)
        yield b""

    async def aclose(self):
        pass


@respx.mock
async def test_interruption_cancels_stream_and_closes_turn():
    respx.post(HERMES_COMPLETIONS_URL).mock(
        return_value=respx.MockResponse(
            200,
            stream=_StallingSSEStream(sse((None, chunk("Vou verificar o projeto")))),
        )
    )
    service = make_service()

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

        # First text frame flows while Hermes "keeps talking" (skip the
        # LLMServiceMetadataFrame the service emits at start-up)...
        frame = await asyncio.wait_for(received_down.get(), timeout=10)
        while not isinstance(frame, LLMTextFrame):
            frame = await asyncio.wait_for(received_down.get(), timeout=10)
        assert frame.text == "Vou verificar o projeto"

        # ...then the user barges in: the VAD would broadcast an interruption.
        await source.queue_frame(InterruptionFrame())

        # The in-flight completion is cancelled and the turn still closes.
        end = await asyncio.wait_for(received_down.get(), timeout=10)
        while not isinstance(end, LLMFullResponseEndFrame):
            end = await asyncio.wait_for(received_down.get(), timeout=10)
    finally:
        await runner.cancel()
        with suppress(asyncio.CancelledError):
            await run_task
