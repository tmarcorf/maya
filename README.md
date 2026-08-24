# Maya

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
                  ├─ TTS (Kokoro local / Qwen3-TTS local GPU / ElevenLabs cloud)
                  └─ playback (speaker)
```

Two processes, a clear division of responsibilities:

- **Pipecat** handles: audio, VAD, turn detection, STT, async pipeline, streaming, TTS, interruptions, and metrics.
- **Hermes** handles: reasoning, LLM, tool execution, terminal, browser, memory, skills, and subagents.

Pipecat doesn't duplicate anything Hermes does — Maya is essentially the bridge between voice and agent.

### End-to-end streaming

Hermes' text arrives over SSE and each chunk becomes an `LLMTextFrame`, which Pipecat forwards to the TTS (Kokoro, Qwen3-TTS, or ElevenLabs, via `TTS_PROVIDER`) with **sentence-level aggregation** (native to `TTSService`). TTS starts as soon as the first sentence is complete — no waiting for the full response.

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
- **NVIDIA GPU with CUDA** (required only for `TTS_PROVIDER=qwen3`; Kokoro and ElevenLabs work without it)
- [Hermes Agent](https://github.com/NousResearch/hermes-agent) installed (CLI `hermes`)

## Installation

```bash
cd maya
uv pip install -r requirements.txt      # creates/fills the venv with all deps
                                        # (equivalent to uv sync; includes the CUDA libs)
cp .env.example .env                    # then edit HERMES_API_KEY
```

Dependencies: `pipecat-ai[whisper,kokoro,local,elevenlabs]`, `python-dotenv`, `loguru`, `httpx`, NVIDIA CUDA 12 libs (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`, `nvidia-cuda-runtime-cu12`), `qwen-tts` (pulls torch/torchaudio ~2.5 GB and pins transformers/accelerate) (dev: `pytest`, `pytest-asyncio`, `respx`).

On first run the models are downloaded automatically:
- Whisper (faster-whisper) into the ctranslate2 cache;
- Kokoro (`kokoro-v1.0.onnx` + voices) into `~/.cache/pipecat/kokoro-onnx/`;
- Qwen3-TTS (~1.5–2 GB) into `~/.cache/huggingface` (only when `TTS_PROVIDER=qwen3`).

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

## Qwen3-TTS voice (local, GPU)

Runs **Qwen3-TTS 0.6B** (Apache-2.0) locally on your NVIDIA GPU — no per-use cost, with quality above Kokoro, but **slower** (on consumer GPUs each sentence takes a few seconds to synthesize; the first utterance also pays the model-loading cost at startup). For minimal latency, stick with ElevenLabs.

```env
TTS_PROVIDER=qwen3
QWEN3_MODEL=Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice   # or ...-0.6B-Base (voice cloning)
QWEN3_DEVICE=cuda            # cuda, cuda:0, cpu or auto
QWEN3_DTYPE=bfloat16         # float16, bfloat16 or float32
QWEN3_SPEAKER=Ryan           # default voice (all listed below)
QWEN3_INSTRUCT=              # optional style, e.g.: "Speak slowly and calmly."
```

CustomVoice voices (none are native Portuguese — they speak pt-BR with an accent):

| Voice | Profile | Native language |
|---|---|---|
| Vivian | Young, clear female | Chinese |
| Serena | Soft, gentle female | Chinese |
| Uncle_Fu | Mature, velvety male | Chinese |
| Dylan | Young male (Beijing) | Chinese |
| Eric | Lively male (Chengdu) | Chinese |
| Ryan | Dynamic, rhythmic male | English |
| Aiden | Sunny American male | English |
| Ono_Anna | Playful Japanese female | Japanese |
| Sohee | Warm Korean female | Korean |

**Voice cloning** (`-Base` model): clone a voice from a ~3s reference audio — this is the way to get a truly native Portuguese voice:

```env
QWEN3_MODEL=Qwen/Qwen3-TTS-12Hz-0.6B-Base
QWEN3_REF_AUDIO=/path/to/ref.wav   # local file or URL (~3s)
QWEN3_REF_TEXT=transcription of the audio     # empty = just the timbre, no transcription
```

Advanced options: `QWEN3_ATTN_IMPLEMENTATION` (empty = sdpa; or `flash_attention_2`, requires flash-attn installed), `QWEN3_MAX_NEW_TOKENS` (default 4096), `QWEN3_TOP_P`.

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
| No Qwen3 audio | Check `nvidia-smi` (GPU visible?) and the "Loading Qwen3-TTS model..." log line; the model download (~1.5–2 GB) only happens on first run, to `~/.cache/huggingface` — offline machines fail at startup |
| `SoX could not be found` warning on Qwen3 | Harmless — the SoX binary is only used by the 25 Hz tokenizer of the 1.7B models; the 0.6B (12 Hz) doesn't need it |
| `CUDA out of memory` on Qwen3 | Reduce `QWEN3_MAX_NEW_TOKENS` (e.g. 2048) or use `QWEN3_DTYPE=float16` |
| Slow first utterance from Qwen3 | Expected: the model loads at startup and synthesis on consumer GPUs is slower than real time (RTF > 1) — use ElevenLabs for minimal latency |
| High latency | `STT_MODEL=base` (or `tiny`), `STT_COMPUTE_TYPE=int8`, and less silence time in the VAD |
| Wake word doesn't trigger | Check `WAKE_WORD_ENABLED=true` and the phrases in `WAKE_WORD_PHRASES` (separated by `;`); punctuation, accents, and the "Maya"/"Maia" spellings are already normalized automatically — if it still doesn't wake, run with `LOG_LEVEL=DEBUG` and look at the Whisper transcriptions (`STT`/`wake phrase detected`) to see how it's transcribing the phrase |
| Truncated/interrupted responses | Check the microphone (the VAD may be interpreting noise as barge-in) |

## Roadmap

- Wake word, advanced barge-in, streaming STT
- WebRTC/WebSocket transports (web and mobile) — the architecture already isolates the transport
- Web interface and multiple users
- Advanced observability (end-to-end metrics)

The original project spec is in `docs/Implementação de agente de voz com Pipecat + Hermes Agent.md`.
