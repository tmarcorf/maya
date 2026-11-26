from __future__ import annotations

import pytest
from livekit.agents import ToolError

from maya_agent.tools.calculator import build_calculator_tool, calculate_expression


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("2 + 2", 4),
        ("2 + 3 * 4", 14),
        ("(2 + 3) * 4", 20),
        ("10 / 4", 2.5),
        ("10 // 3", 3),
        ("10 % 3", 1),
        ("2 ** 8", 256),
        ("-5 + 2", -3),
        ("-2 ** 2", -4),
    ],
)
async def test_calculator_evaluates_basic_expressions(
    expression: str, expected: int | float
) -> None:
    result = await build_calculator_tool()(expression)

    assert result["expression"] == expression
    assert result["result"] == expected


def test_calculator_converts_integral_float_to_int() -> None:
    assert calculate_expression("8 / 4")["result"] == 2


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "   ",
        "2 +",
        "abc + 1",
        "abs(-1)",
        "__import__('os')",
        "2 ** 1000",
        "1 / 0",
        "(-1) ** 0.5",
    ],
)
def test_calculator_rejects_invalid_or_unsafe_expressions(expression: str) -> None:
    with pytest.raises(ToolError):
        calculate_expression(expression)


def test_calculator_rejects_long_expressions() -> None:
    with pytest.raises(ToolError):
        calculate_expression("1+" * 200 + "1")
