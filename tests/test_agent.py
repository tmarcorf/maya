from __future__ import annotations

from livekit.agents import AgentServer

from maya_agent.agent import build_server


def test_build_server_returns_agent_server() -> None:
    assert isinstance(build_server(), AgentServer)
