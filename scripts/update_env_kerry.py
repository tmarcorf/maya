"""Update Polaris .env with the frozen Kerry Condon Qwen3-TTS setup.

Preserves all other lines (including secrets) verbatim. Prints only the
names of changed keys, never values.
"""
import re
from pathlib import Path

ENV = Path("/home/tmarcorf/Documentos/dev/polaris/.env")

# key -> new value ("" means empty value, i.e. timbre-only mode)
UPDATES = {
    "TTS_PROVIDER": "qwen3",
    "QWEN3_MODEL": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
    "QWEN3_REF_AUDIO": "/home/tmarcorf/kerry_condon/ref_clip_20s.wav",
    "QWEN3_REF_TEXT": "",
    "HF_HOME": "/home/tmarcorf/qwen3tts/hf",
}

lines = ENV.read_text(encoding="utf-8").splitlines()
changed = []
seen = set()

for i, line in enumerate(lines):
    m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
    if m and m.group(1) in UPDATES:
        key = m.group(1)
        seen.add(key)
        new_line = f"{key}={UPDATES[key]}"
        if line != new_line:
            lines[i] = new_line
            changed.append(key)

for key, value in UPDATES.items():
    if key not in seen:
        lines.append(f"{key}={value}")
        changed.append(key)

ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("changed:", ", ".join(changed) if changed else "(none)")
