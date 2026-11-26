from __future__ import annotations

import pytest

from maya_agent.config import MayaSettings
from maya_agent.instructions import (
    build_instructions,
    greeting_instructions,
    load_persona,
)


def test_load_persona_strips_whitespace(tmp_path) -> None:
    prompt_path = tmp_path / "maya.md"
    prompt_path.write_text("\n  Persona de teste.  \n", encoding="utf-8")

    assert load_persona(prompt_path) == "Persona de teste."


def test_missing_prompt_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="Prompt file not found"):
        load_persona(tmp_path / "missing.md")


def test_empty_prompt_raises(tmp_path) -> None:
    prompt_path = tmp_path / "maya.md"
    prompt_path.write_text("   \n", encoding="utf-8")

    with pytest.raises(ValueError, match="Prompt file is empty"):
        load_persona(prompt_path)


def test_build_instructions_appends_language_directive(tmp_path) -> None:
    prompt_path = tmp_path / "maya.md"
    prompt_path.write_text("Persona de teste.", encoding="utf-8")
    settings = MayaSettings(
        language="pt-BR",
        prompt_path=prompt_path,
        timezone="America/Sao_Paulo",
    )

    instructions = build_instructions(settings)

    assert instructions.startswith("Persona de teste.")
    assert "Brazilian Portuguese" in instructions


def test_greeting_instructions_use_language(tmp_path) -> None:
    settings = MayaSettings(
        language="en-US",
        prompt_path=tmp_path / "unused.md",
        timezone="America/Sao_Paulo",
    )

    greeting = greeting_instructions(settings)

    assert "English" in greeting
    assert "Maya" in greeting
    assert "one short sentence" in greeting
