from __future__ import annotations

from typing import Any

from maya_agent.approvals import ApprovalBroker, parse_approval, resolution_body


def _payload() -> dict[str, Any]:
    return {
        "run_id": "run-1",
        "request_id": "req-1",
        "command": "rm -rf /tmp/example",
        "description": "Comando perigoso",
        "choices": ["once", "deny"],
        "execution_generation": 3,
    }


def test_parse_approval() -> None:
    approval = parse_approval(_payload())

    assert approval is not None
    assert approval.run_id == "run-1"
    assert approval.request_id == "req-1"
    assert approval.command == "rm -rf /tmp/example"
    assert approval.choices == ("once", "deny")
    assert approval.execution_generation == 3


def test_parse_approval_requires_run_and_request() -> None:
    assert parse_approval({"run_id": "run-1"}) is None
    assert parse_approval({"request_id": "req-1"}) is None


def test_resolution_body_includes_generation() -> None:
    approval = parse_approval(_payload())
    assert approval is not None

    assert resolution_body(approval, "once") == {
        "choice": "once",
        "request_id": "req-1",
        "execution_generation": 3,
    }


async def test_broker_resolves_with_injected_poster() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def poster(run_id: str, body: dict[str, Any]) -> bool:
        calls.append((run_id, body))
        return True

    broker = ApprovalBroker(
        base_url="http://127.0.0.1:8642/p/maya-voice/v1",
        api_key="hermes-key",
        port=0,
        notify=False,
        poster=poster,
    )
    broker.publish(_payload())
    approval = broker.pending[0]

    assert await broker.resolve(approval, "deny") is True
    assert calls == [
        (
            "run-1",
            {"choice": "deny", "request_id": "req-1", "execution_generation": 3},
        )
    ]
    assert broker.pending == ()


async def test_broker_rejects_unknown_choice() -> None:
    async def poster(run_id: str, body: dict[str, Any]) -> bool:
        return True

    broker = ApprovalBroker(
        base_url="http://127.0.0.1:8642/p/maya-voice/v1",
        api_key="hermes-key",
        port=0,
        notify=False,
        poster=poster,
    )
    broker.publish(_payload())
    approval = broker.pending[0]

    assert await broker.resolve(approval, "always") is False
    assert broker.pending == (approval,)
