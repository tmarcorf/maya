#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ -x .venv/bin/python ]; then
  VENV_SITE=$(.venv/bin/python -c "import site; print(site.getsitepackages()[0])")
  if [ -d "$VENV_SITE/nvidia" ]; then
    NV_LIBS=$(find "$VENV_SITE/nvidia" -maxdepth 2 -type d -name lib -print | paste -sd: -)
    export LD_LIBRARY_PATH="${NV_LIBS}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  fi
fi

exec uv run python -m maya_agent "$@"
