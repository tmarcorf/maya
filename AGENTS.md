# Maya

Maya is the realtime voice layer for the Hermes Agent. The stack is fixed:
faster-whisper (local STT), LiveKit turn-taking/VAD, ElevenLabs (TTS), and the
Hermes API Server as the LLM/tool runner. Hermes owns the transcript, memory,
tools, skills, and cron; Maya owns only audio I/O and the voice turn loop.
DeepSeek is configured inside the Hermes profile, not inside Maya. Do not add
provider selectors or factories until a second adapter for the same capability
exists.

## Commands

```bash
uv sync
uv run python -m livekit.agents download-files
./run.sh console
./run.sh dev
uv run pytest
uvx ruff check .
```

`run.sh` sets `LD_LIBRARY_PATH` from the pip-installed NVIDIA wheels before
starting Python. Use it for anything that loads faster-whisper on CUDA.

## Layout

- `src/maya_agent/config.py`: immutable settings grouped by capability.
  `load_settings(env)` is pure; `.env` loading happens in `agent.main()`.
- `src/maya_agent/agent.py`: composition root only. Creates `AgentServer`,
  registers prewarm and the RTC session, and sends the greeting.
- `src/maya_agent/session.py`: builds `Agent`, `AgentSession`, and turn
  handling from settings. Wires `HermesLLM` progress/approval events.
- `src/maya_agent/llm_hermes.py`: the only LLM adapter. Streams SSE from the
  Hermes API server, sends only the latest user turn, and sets
  `X-Hermes-Session-Id`/`X-Hermes-Session-Key`.
- `src/maya_agent/approvals.py`: local approval page and `notify-send` fallback
  for `approval.request` events. Posts decisions to
  `/v1/runs/{run_id}/approval`.
- `src/maya_agent/stt_whisper.py`: `WhisperSTT` protocol adapter plus
  `FasterWhisperTranscriber` (model cache, CUDA fallback, inference lock).
- `src/maya_agent/tts_elevenlabs.py`: ElevenLabs adapter.
- `src/maya_agent/instructions.py`: voice prompt loading and language directive.
- `src/maya_agent/latency.py`: structured turn latency logging from session and
  LLM events.
- `prompts/maya.md`: ephemeral voice-format contract, resolved through
  `MAYA_PROMPT_PATH`. The persona lives in the Hermes profile's `SOUL.md`.
- `src/maya_agent/tools/`: legacy PHP-era tool modules kept in the tree but not
  wired to `Agent`. Hermes executes tools now; do not re-enable these without a
  deliberate decision.

## Hermes profile

- Profile id: `maya-voice`. The default Hermes profile already has the display
  name "Maya", so the voice profile uses a distinct id.
- API endpoint: `http://127.0.0.1:8642/p/maya-voice/v1`.
- `API_SERVER_ENABLED=true` and a per-profile `API_SERVER_KEY` in
  `~/.hermes/profiles/maya-voice/.env`.
- `platform_toolsets.api_server` lists every Hermes toolset except `stt`/`tts`
  (Maya owns audio); `terminal.backend` is `local`; `agent.reasoning_effort` is
  `"none"` for latency.
- Hermes STT/TTS are disabled (`stt.enabled: false`, `voice.auto_tts: false`).
- Market/stocks use the official `finance/stocks` skill. Weather uses web search
  unless the optional `weather` plugin is enabled (it needs Rust).
- Restart after profile changes: `hermes gateway restart`.

## Invariants

- Do not fork Hermes. Configure the profile and upgrade with `hermes update`.
- Maya sends only the **latest** user utterance plus a fixed per-room
  `X-Hermes-Session-Id` and a per-user `X-Hermes-Session-Key`. Do not resend the
  LiveKit chat history; Hermes loads its own transcript from `state.db`.
- Hermes owns tools, memory, skills, and the transcript. Maya registers no
  local function tools.
- There is no direct DeepSeek (or other provider) LLM adapter in Maya. The only
  LLM path is `HermesLLM`.
- Tool progress is spoken out of band with
  `session.say(..., add_to_chat_ctx=False)`; it must not enter the transcript.
- Dangerous commands stay approval-gated. Hermes Desktop is the primary approval
  surface; `approvals.py` is the headless fallback. Never disable approvals for
  unattended voice runs.
- If Hermes is down, speak a short error and retry once. Do not fall back to a
  direct LLM.
- `.env` is gitignored and must stay out of commits.
- Tests must not load `.env`, download models, or make network calls. Inject a
  fake SSE transport/stream for `HermesLLM` tests.
- Keep one concrete adapter per capability. Add a factory/union only when a second
  adapter exists.

## Adding a provider later

- New LLM/model/tool provider: configure it in the Hermes profile, not in Maya.
  Maya only needs a new voice I/O adapter if a second STT or TTS provider exists.
- New voice I/O adapter: add a settings group in `config.py`, a builder module
  next to the current adapter, wire it in `session.py`, and update `.env.example`,
  README, and tests.
