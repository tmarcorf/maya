"""Custom control frames for the Maya pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from pipecat.frames.frames import ControlFrame


@dataclass
class ToolActivityFrame(ControlFrame):
    """A Hermes tool progress event, forwarded downstream for UI mirroring.

    Carries the payload of the ``event: hermes.tool.progress`` SSE event so
    observer processors (the desktop bridge) can publish it. It is a control
    frame: the TTS and transports pass it through untouched, and it is never
    spoken (spec §15).
    """

    tool: str = ""
    label: str = ""
    emoji: str = ""
    tool_call_id: str = ""
    status: str = ""
