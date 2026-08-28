#!/usr/bin/env bash
# Prepara desktop/backend-staging/ com o backend Python + venv AUTOCONTIDO,
# para o electron-builder embarcar como extraResources (resources/backend).
#
# O ponto crítico: o bin/python do venv uv é um symlink para um interpretador
# gerenciado pelo uv (~/.local/share/uv/python/...) — sem copiar o binário
# real + stdlib, o .deb instalado em outra máquina (ou após remover o uv)
# quebraria no primeiro launch.
#
# Uso: npm run prepare:backend   (cwd = desktop/)

set -euo pipefail
cd "$(dirname "$0")/.."

STAGE=backend-staging
ROOT=$(cd .. && pwd)   # raiz do repo, absoluta (link-dest do rsync resolve relativo ao destino)

echo "▶ Preparando $STAGE/ ..."
rm -rf "$STAGE"
mkdir -p "$STAGE"

# 1. Código — lista explícita, nunca `cp .` (e nunca o .env com chaves reais).
cp -r "$ROOT/app.py" "$ROOT/config" "$ROOT/pipeline" "$ROOT/utils" \
      "$ROOT/requirements.txt" "$ROOT/.env.example" "$STAGE/"
find "$STAGE" -name __pycache__ -type d -prune -exec rm -rf {} +
find "$STAGE" -name '*.pyc' -delete

# 2. Venv (2,1 GB — rebuilds usam hardlinks via --link-dest p/ não copiar de novo).
rsync -a --link-dest="$ROOT/.venv" --exclude '__pycache__' --exclude '*.pyc' \
      "$ROOT/.venv/" "$STAGE/venv/"

# 3. Interpretador autocontido.
UV_PYTHON=$(readlink -f "$STAGE/venv/bin/python")
UV_ROOT=$(dirname "$(dirname "$UV_PYTHON")")   # .../cpython-3.13-...-gnu
echo "  ↳ interpretador uv: $UV_PYTHON"
# O python3.13 do venv uv é hardlink do interpretador gerenciado — remove o
# link e copia o binário real para o venv staged (autocontido).
rm -f "$STAGE/venv/bin/python3.13"
cp -L "$UV_PYTHON" "$STAGE/venv/bin/python3.13"
ln -sf python3.13 "$STAGE/venv/bin/python"
ln -sf python3.13 "$STAGE/venv/bin/python3"
rsync -a "$UV_ROOT/lib/" "$STAGE/venv/lib/"
sed -i '/^home = /d' "$STAGE/venv/pyvenv.cfg"

# 4. Smoke test — o venv staged precisa importar sem nenhum ambiente externo.
echo "  ↳ smoke test do venv staged..."
"$STAGE/venv/bin/python" -c "import sys, pipecat; print('  ✓ python', sys.version.split()[0], '— pipecat ok')"

echo "✓ $STAGE pronto ($(du -sh "$STAGE" | cut -f1))"
