#!/usr/bin/env bash
# Maya — sobe o Hermes gateway (se ainda não estiver no ar) e o agente de voz.
# Também expõe as libs CUDA (instaladas via pip em site-packages/nvidia):
# sem isso, o ctranslate2 não acha libcublas.so.12 quando STT_DEVICE=cuda.
# O LD_LIBRARY_PATH precisa estar setado ANTES do Python iniciar.
set -euo pipefail
cd "$(dirname "$0")"

# URL de health do Hermes — respeita HERMES_BASE_URL do .env.
HERMES_BASE_URL=$(grep -E '^HERMES_BASE_URL=' .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '[:space:]' || true)
HERMES_BASE_URL=${HERMES_BASE_URL:-http://127.0.0.1:8642/v1}
HERMES_HEALTH_URL="${HERMES_BASE_URL%/}/health"
HERMES_LOG="${TMPDIR:-/tmp}/maya-hermes.log"

# 1. Hermes gateway — reutiliza um que já esteja no ar.
if ! curl -fsS --max-time 2 "$HERMES_HEALTH_URL" >/dev/null 2>&1; then
    echo "▶ Subindo hermes gateway (log: $HERMES_LOG) ..."
    hermes gateway >"$HERMES_LOG" 2>&1 &
    HERMES_PID=$!
    trap 'kill "$HERMES_PID" 2>/dev/null; wait "$HERMES_PID" 2>/dev/null' EXIT

    # Aguarda o gateway responder (o app tem health check próprio).
    for _ in $(seq 1 30); do
        if curl -fsS --max-time 2 "$HERMES_HEALTH_URL" >/dev/null 2>&1; then
            echo "✓ Hermes gateway no ar."
            break
        fi
        if ! kill -0 "$HERMES_PID" 2>/dev/null; then
            echo "✗ hermes gateway morreu ao subir. Últimas linhas do log:"
            tail -20 "$HERMES_LOG"
            exit 1
        fi
        sleep 1
    done
    if ! curl -fsS --max-time 2 "$HERMES_HEALTH_URL" >/dev/null 2>&1; then
        echo "✗ Hermes gateway não respondeu em 30s. Últimas linhas do log:"
        tail -20 "$HERMES_LOG"
        exit 1
    fi
else
    echo "✓ Hermes gateway já está no ar."
fi

# 2. Libs CUDA p/ o Whisper em GPU.
VENV_SITE=$(.venv/bin/python -c "import site; print(site.getsitepackages()[0])")
NV_LIBS=$(find "$VENV_SITE/nvidia" -maxdepth 2 -type d -name lib -print | paste -sd: -)
export LD_LIBRARY_PATH="${NV_LIBS}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# 3. O agente de voz. Ctrl+C encerra tudo (o trap derruba o gateway junto).
uv run python app.py
