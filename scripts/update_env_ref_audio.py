"""Update Maya .env QWEN3_REF_AUDIO to the Downloads copy."""
import re
from pathlib import Path

ENV = Path("/home/tmarcorf/Documentos/dev/maya/.env")
NEW_REF = "/home/tmarcorf/Downloads/kerry_condon_ref_clip_20s.wav"

lines = ENV.read_text(encoding="utf-8").splitlines()
changed = False
for i, line in enumerate(lines):
    m = re.match(r"^(QWEN3_REF_AUDIO)\s*=", line)
    if m:
        new_line = f"QWEN3_REF_AUDIO={NEW_REF}"
        if line != new_line:
            lines[i] = new_line
            changed = True
        break
else:
    lines.append(f"QWEN3_REF_AUDIO={NEW_REF}")
    changed = True

ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("changed" if changed else "already set")
