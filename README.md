# Maya
<img width="178" height="176" alt="image" align="center" src="https://github.com/user-attachments/assets/359c5c2b-c33a-4525-b1e2-a1980a47bfc1" />


Local voice assistant powered by **Pipecat** (voice, STT, TTS, streaming) and **Hermes Agent** (agentic brain: LLM, tools, terminal, browser, memory). Maya is the bridge between the two — you speak, Hermes thinks and executes, and Maya answers with voice, **without waiting for the full response to start speaking**.

## Architecture

```
You  ──speak──▶  PIPECAT                      HERMES AGENT (separate process)
                  ├─ audio capture (mic)       ┌─ LLM + reasoning
                  ├─ VAD / turn detection      ├─ Tools / Terminal / Browser
                  ├─ STT (Whisper, local)      ├─ Memory / Skills / Subagents
                  ├─ voice session         ──▶ └─ http://127.0.0.1:8642/v1
                  │      streaming SSE ◀────────┘  (POST /v1/chat/completions)
                  ├─ chunks → LLMTextFrame
                  ├─ TTS (Kokoro local / ElevenLabs cloud)
                  └─ playback (speaker)
```

Two processes, a clear division of responsibilities:

- **Pipecat** handles: audio, VAD, turn detection, STT, async pipeline, streaming, TTS, interruptions, and metrics.
- **Hermes** handles: reasoning, LLM, tool execution, terminal, browser, memory, skills, and subagents.

Pipecat doesn't duplicate anything Hermes does — Maya is essentially the bridge between voice and agent.

### End-to-end streaming

Hermes' text arrives over SSE and each chunk becomes an `LLMTextFrame`, which Pipecat forwards to the TTS (Kokoro or ElevenLabs, via `TTS_PROVIDER`) with **sentence-level aggregation** (native to `TTSService`). TTS starts as soon as the first sentence is complete — no waiting for the full response.

### Session

The conversation is held **exclusively by Hermes**: the first request doesn't send an `X-Hermes-Session-Id` (Hermes creates a session and echoes the id in the response header); subsequent requests reuse that id. The history is never duplicated in Pipecat — each turn only the user's new message goes over the wire. The local conversation id is `voice-session-<uuid>`.

### Tool events

Hermes emits `event: hermes.tool.progress` during tool executions. Maya **logs these events** (observability) and **never** sends them to the TTS — you only hear the agent's final response.

### Interruption (barge-in)

If you start speaking while Maya is responding, Pipecat's VAD fires an `InterruptionFrame`, the in-flight inference is cancelled, and the HTTP connection to Hermes is closed — which makes Hermes cancel the agentic turn. Your new speech is then processed normally.

## Prerequisites

- Python 3.11+ (managed by uv)
- [uv](https://docs.astral.sh/uv/)
- **Linux**: `portaudio19-dev` (to compile PyAudio for the local transport):
  ```bash
  sudo apt-get install -y portaudio19-dev
  ```
- Microphone and audio output
- [Hermes Agent](https://github.com/NousResearch/hermes-agent) installed (CLI `hermes`)

## Installation

```bash
cd maya
uv pip install -r requirements.txt      # creates/fills the venv with all deps
                                        # (equivalent to uv sync; includes the CUDA libs)
cp .env.example .env                    # then edit HERMES_API_KEY
```

Dependencies: `pipecat-ai[whisper,kokoro,local,elevenlabs]`, `python-dotenv`, `loguru`, `httpx`, NVIDIA CUDA 12 libs (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`, `nvidia-cuda-runtime-cu12`) (dev: `pytest`, `pytest-asyncio`, `respx`).

On first run the models are downloaded automatically:
- Whisper (faster-whisper) into the ctranslate2 cache;
- Kokoro (`kokoro-v1.0.onnx` + voices) into `~/.cache/pipecat/kokoro-onnx/`.

## Hermes

Enable the API server in `~/.hermes/.env`:

```env
API_SERVER_ENABLED=true
API_SERVER_KEY=any-local-key
```

The gateway can be started manually (the API server starts with it) or automatically by `./maya.sh`:

```bash
hermes gateway
# [API Server] API server listening on http://127.0.0.1:8642
```

Quick test:

```bash
curl -N http://127.0.0.1:8642/v1/health
```

Use the same `API_SERVER_KEY` for the `HERMES_API_KEY` in this project's `.env`. Don't expose the API server outside 127.0.0.1.

## Running

```bash
./maya.sh
```

`maya.sh` does everything: starts `hermes gateway` (if it isn't already up — reuses a running one), waits for the health check to respond, adjusts `LD_LIBRARY_PATH` for the CUDA libs installed via pip (Whisper's ctranslate2 needs them when `STT_DEVICE=cuda`) and then runs the agent. Ctrl+C shuts everything down — including the gateway it started. With `STT_DEVICE=cpu` you can run `uv run python app.py` directly (with Hermes already up).

Speak into the microphone. Maya detects the end of the turn, transcribes, sends it to Hermes and starts responding while the response is still being generated. Ctrl+C to quit.

To use an ElevenLabs voice instead of Kokoro, configure in `.env`:

```env
TTS_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=...   # API key
ELEVENLABS_VOICE_ID=...  # voice id (premade or cloned)
```

## Desktop companion (Electron)

Besides the terminal, Maya exposes a **local WebSocket bridge** (`ws://127.0.0.1:8686`, configurable via `BRIDGE_WS_PORT`) that mirrors the conversation state to the desktop app in `desktop/` (3D orb, chat, wake word toggle). It publishes events (`hello`, `state`, `user_transcript`, `agent_text`/`agent_text_end`, `tool_activity`, `interruption`, `audio_level`, `wake_state`) and accepts commands with ack: `get_state`, `set_wake_word_enabled`, `ping`. One client at a time.

With `./maya.sh` running, you can inspect the bridge with:

```bash
websocat ws://127.0.0.1:8686
```

## Wake word

Maya can stay "asleep" until it hears an activation phrase (detected in the Whisper transcription — no extra model):

```env
WAKE_WORD_ENABLED=true
WAKE_WORD_PHRASES=Hey Maya;Yo Maya;Maya, you there?   # ';'-separated list
WAKE_WORD_TIMEOUT=10     # seconds of inactivity before going back to sleep
```

Behavior: while asleep, nothing goes to Hermes (speech is discarded); upon hearing one of the phrases, Maya wakes up and the conversation flows normally; after `WAKE_WORD_TIMEOUT` seconds without speech, it goes back to sleep. Matching is tolerant: it ignores case, punctuation, and accents (Whisper often transcribes "maia" instead of "Maya" and drops accents — both variants are accepted automatically).

## Tests

```bash
uv run pytest -q
```

The suite covers: configuration, pipeline creation, SSE parsing, chunk-to-frame conversion, `[DONE]`, HTTP errors, session, and interruption/cancellation — all with a fake Hermes (respx), no network, no real models.

## Troubleshooting

| Symptom | Solution |
|---|---|
| `Hermes API server is offline` | Run `hermes gateway` and check `API_SERVER_ENABLED=true` in `~/.hermes/.env` |
| HTTP 401 from Hermes | `HERMES_API_KEY` in `.env` must equal `API_SERVER_KEY` in `~/.hermes/.env` |
| Port 8642 in use | Change `API_SERVER_PORT` in `~/.hermes/.env` and `HERMES_BASE_URL` in `.env` |
| No audio capture | List devices and use `AUDIO_IN_DEVICE`/`AUDIO_OUT_DEVICE` (PyAudio indices) |
| Install error (`portaudio.h`) | `sudo apt-get install -y portaudio19-dev` and run `uv sync` again |
| Whisper model download slow | The first turn downloads the model; use `STT_MODEL=base` for modest machines |
| `Library libcublas.so.12 is not found` | Run via `./maya.sh` (exposes the pip CUDA libs via `LD_LIBRARY_PATH`) or use `STT_DEVICE=cpu` |
| No Kokoro audio | Check `~/.cache/pipecat/kokoro-onnx/` (model + voices); test `TTS_VOICE=pm_alex` |
| No ElevenLabs audio (log shows TTS watchdog error) | **Library** voices (e.g. Fernanda) require a paid plan: the API returns `402 paid_plan_required` on free. On free, only **premade** voices work via API — test with `curl -X POST https://api.elevenlabs.io/v1/text-to-speech/{voice}?model_id=eleven_flash_v2_5 -H "xi-api-key: $ELEVENLABS_API_KEY" -H "Content-Type: application/json" -d '{"text":"hi"}'` |
| High latency | `STT_MODEL=base` (or `tiny`), `STT_COMPUTE_TYPE=int8`, and less silence time in the VAD |
| Wake word doesn't trigger | Check `WAKE_WORD_ENABLED=true` and the phrases in `WAKE_WORD_PHRASES` (separated by `;`); punctuation, accents, and the "Maya"/"Maia" spellings are already normalized automatically — if it still doesn't wake, run with `LOG_LEVEL=DEBUG` and look at the Whisper transcriptions (`STT`/`wake phrase detected`) to see how it's transcribing the phrase |
| Truncated/interrupted responses | Check the microphone (the VAD may be interpreting noise as barge-in) |

## Roadmap

- Wake word, advanced barge-in, streaming STT
- WebRTC/WebSocket transports (web and mobile) — the architecture already isolates the transport
- Web interface and multiple users
- Advanced observability (end-to-end metrics)

The original project spec is in `docs/Implementação de agente de voz com Pipecat + Hermes Agent.md`.
