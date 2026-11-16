# AGENTS.md

## What this is

Maya is a local voice assistant split across processes:

- **Python/Pipecat backend** (`app.py`): mic capture, VAD, STT, TTS, playback, and a local WebSocket bridge.
- **Hermes Agent** (external `hermes gateway`): LLM, tools, terminal, memory; OpenAI-compatible SSE API at `HERMES_BASE_URL` (base includes `/v1`; health is `GET {base}/health`).
- **`desktop/`**: Electron/React companion (3D orb, chat mirror, wake toggle). Not required to use voice.

Python packages are top-level (`config`, `pipeline`, `utils`), not under `src/`. Run Python commands from the repo root.

## Setup

- Use `uv sync` for development: it installs the dev group plus `websockets`. `requirements.txt` is runtime-only and omits `pytest`/`respx`/`websockets`.
- `cp .env.example .env`; `HERMES_API_KEY` must equal `API_SERVER_KEY` in `~/.hermes/.env` (with `API_SERVER_ENABLED=true`).
- Linux: install `portaudio19-dev` before the PyAudio dependency.
- Run real voice with `./maya.sh`. It reuses/starts `hermes gateway`, waits for health, and exports pip-installed CUDA libs via `LD_LIBRARY_PATH`. For `STT_DEVICE=cuda`, use `./maya.sh`; `uv run python app.py` is only safe with Hermes already up and CPU STT.
- First real run downloads Whisper/Kokoro models; tests never do.

## Commands

```bash
uv run pytest -q                                  # full suite, offline, fast
uv run pytest tests/test_bridge.py::test_name -q  # single test
uvx ruff check .                                  # lint (ruff is not a project dependency)
uv run python app.py                              # only with Hermes up + STT_DEVICE=cpu
./maya.sh                                         # recommended end-to-end run
```

All npm commands run from `desktop/`:

```bash
npm run mock        # fake bridge on ws://127.0.0.1:8686
npm run dev:web     # renderer only, http://localhost:5174
npm run dev         # Electron + Vite; spawns the Python backend if the bridge port is free
npm run build       # TS typecheck + renderer/electron production build
npm run dist:linux  # package AppImage/deb (runs prepare-backend.sh, ~2 GB staging)
```

Desktop E2E: after `npm run build`, start `npm run mock`, then run `node scripts/verify-electron.mjs`.

There is no CI config and no desktop test suite. `desktop/README.md` mentions `npm test`, but `package.json` has no `test` script; use `npm run build` as desktop verification.

## Architecture notes

- Flow: `app.py` -> `config/settings.py` -> `pipeline/voice_pipeline.py` (`build_services`/`build_pipeline`/`run_voice_agent`). Components are injectable so tests use fakes instead of loading Whisper/Kokoro.
- Pipeline order is load-bearing: STT -> `UserTranscriptObserver` -> user aggregator -> Hermes LLM -> TTS -> `VoiceBridge` -> output -> assistant aggregator. The observers must stay on those sides of the aggregators; moving them breaks transcript/state mirroring.
- `pipeline/hermes.py` is a custom `httpx` SSE client, not the OpenAI SDK, because Hermes emits `event: hermes.tool.progress`. Only the newest user message is sent per turn; history lives in Hermes via `X-Hermes-Session-Id`. Closing the HTTP stream is the barge-in/cancel mechanism.
- Tool progress is logged and mirrored as `ToolActivityFrame` for the UI; it must never reach TTS.
- Changing the bridge protocol requires updating `pipeline/bridge.py`, `desktop/src/shared/protocol.ts`, and `desktop/scripts/mock-bridge.mjs` together.
- `desktop/electron/` owns the bridge WebSocket; the renderer consumes it through preload IPC. Do not open a second WS client in the renderer.
- Desktop dev uses the repo `.env` and `.venv/bin/python`; packaged builds use `MAYA_ENV_FILE` (writable userData `.env`) and `resources/backend/venv`. `MAYA_SKIP_BACKEND=1` prevents Electron from spawning the backend.
- `desktop/scripts/prepare-backend.sh` copies an explicit list (`app.py`, `config`, `pipeline`, `utils`, `requirements.txt`, `.env.example`). Add any new top-level Python module there or it will not ship.
- `Settings` is frozen; runtime wake on/off lives in `WakeWordController`. Wake phrases are `;`-separated and normalized (punctuation, accents, `maya`<->`maia`) in `_expand_wake_phrases`.
- There is no system prompt in Pipecat by design: Hermes owns persona and memory. Do not add developer/system messages to the Pipecat context.

## Testing conventions

- Tests are offline: Hermes is mocked with `respx`, and no real audio/model is loaded.
- `pytest` config: `asyncio_mode=auto` (no `@pytest.mark.asyncio` needed), `pythonpath=["."]`.
- Import helpers directly from `conftest` (`make_settings`, `make_service`, `make_context`, `sse`, `chunk`).
- Use `respx.MockResponse`; `respx.Response` was removed in respx 0.23.
- Use `run_test()` from `pipecat.tests.utils` for pipeline/service tests.
- The autouse `no_dotenv` fixture disables `.env` loading; don't rely on local `.env`.
- Pipecat deprecation/runtime warnings in the suite are upstream noise, not regressions.
- Ruff may report an unused `pytest` import in `tests/test_pipeline.py`; it predates your change.

## Gotchas

- Adding a Python dependency means updating both `pyproject.toml` and `requirements.txt`; `uv.lock` is committed.
- ElevenLabs TTS sets `push_text_frames=False`, so `agent_text`/`TTSTextFrame` mirroring is unavailable with that provider; Kokoro is the default.
- In Electron, the wake toggle is never optimistic: UI state changes only on the bridge ack.
- Orb rendering is Three.js vanilla driven by refs/Zustand subscriptions; don't move per-frame audio updates into React state.
- Do not search or edit generated/vendored dirs: `.venv/`, `desktop/node_modules/`, `desktop/backend-staging/`, `desktop/dist*/`, `desktop/release/`.
- `.env` is ignored and must not be committed.
- Inline comments/docstrings mix English and Portuguese; match the surrounding file.
- Commits follow Conventional Commits (`feat:`, `fix:`, `refactor:`, `chore:`).
- Deeper design notes are in `docs/maya-documentacao.md`; some counts/commands there are stale, so prefer code, `pyproject.toml`, and `package.json`.
