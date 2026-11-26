from __future__ import annotations

import ast
from typing import Any

from livekit.agents import ToolError, function_tool, llm

MAX_EXPRESSION_CHARS = 200
MAX_POWER = 100


def _eval_node(node: ast.AST) -> int | float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("unsupported constant")
        return node.value

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_node(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value

    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left)
        right = _eval_node(node.right)

        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise ValueError("division by zero")
            return left / right
        if isinstance(node.op, ast.FloorDiv):
            if right == 0:
                raise ValueError("division by zero")
            return left // right
        if isinstance(node.op, ast.Mod):
            if right == 0:
                raise ValueError("division by zero")
            return left % right
        if isinstance(node.op, ast.Pow):
            if abs(right) > MAX_POWER:
                raise ValueError("exponent too large")
            result = left**right
            if isinstance(result, complex):
                raise ValueError("complex result")
            return result

    raise ValueError("unsupported expression")


def calculate_expression(expression: str) -> dict[str, Any]:
    cleaned = " ".join(expression.split()).strip()
    if not cleaned:
        raise ToolError("Diga qual conta você quer que eu faça.")
    if len(cleaned) > MAX_EXPRESSION_CHARS:
        raise ToolError("Essa conta é longa demais.")

    try:
        tree = ast.parse(cleaned, mode="eval")
        result = _eval_node(tree)
    except Exception as exc:
        raise ToolError("Não consegui calcular essa expressão.") from exc

    if isinstance(result, float) and result.is_integer() and abs(result) < 1e15:
        result = int(result)

    return {"expression": cleaned, "result": result}


def build_calculator_tool() -> llm.Tool:
    @function_tool(name="calculate")
    async def calculate(expression: str) -> dict[str, Any]:
        """Evaluate a basic arithmetic expression.

        Supports numbers, parentheses, +, -, *, /, //, % and **. Use for
        calculations instead of doing mental math.
        """
        return calculate_expression(expression)

    return calculate
