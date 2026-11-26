from __future__ import annotations

from pathlib import Path

from .config import MayaSettings


def load_persona(prompt_path: Path) -> str:
    if not prompt_path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

    persona = prompt_path.read_text(encoding="utf-8").strip()
    if not persona:
        raise ValueError(f"Prompt file is empty: {prompt_path}")
    return persona


def build_instructions(settings: MayaSettings) -> str:
    persona = load_persona(settings.prompt_path)
    return f"{persona}\n\nAlways speak and respond in {settings.language_name}."


def greeting_instructions(settings: MayaSettings) -> str:
    return (
        f"Greet the user warmly in one short sentence in {settings.language_name}, "
        "introduce yourself as Maya, and ask how they are doing."
    )
