# Maya

Realtime voice agent Maya built with LiveKit Agents. Current stack is fixed:
faster-whisper (local STT), DeepSeek (LLM via the OpenAI-compatible plugin),
ElevenLabs (TTS), Tavily (web search/extract; key optional, keyless fallback),
Open-Meteo (weather/forecast), Yahoo Finance (market/stock quotes), plus local
datetime, calculator and Wikipedia tools. Do not add provider selectors or
factories until a second adapter for the same capability exists.

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
  handling from settings.
- `src/maya_agent/stt_whisper.py`: `WhisperSTT` protocol adapter plus
  `FasterWhisperTranscriber` (model cache, CUDA fallback, inference lock).
- `src/maya_agent/llm_deepseek.py`: DeepSeek adapter on top of `openai.LLM`.
- `src/maya_agent/tts_elevenlabs.py`: ElevenLabs adapter.
- `src/maya_agent/tools/__init__.py`: `build_tools(AppSettings)` composes all
  function tools.
- `src/maya_agent/tools/web_search.py`: `TavilySearchClient`,
  `WebSearchClient`, normalized `web_search`, and TTL cache.
- `src/maya_agent/tools/web_extract.py`: `TavilyExtractClient`,
  `WebExtractClient`, normalized `web_extract`, and TTL cache.
- `src/maya_agent/tools/weather.py`: Open-Meteo `get_weather` and
  `get_weather_forecast`.
- `src/maya_agent/tools/market.py`: Yahoo Finance `get_market_summary` and
  `get_stock_quote`.
- `src/maya_agent/tools/time_tool.py`: timezone-aware `get_current_datetime`.
- `src/maya_agent/tools/calculator.py`: safe AST-based `calculate`.
- `src/maya_agent/tools/wikipedia.py`: MediaWiki `wikipedia` summary.
- `src/maya_agent/tools/cache.py`: small in-memory `TTLCache`.
- `src/maya_agent/tools/text.py`: text cleanup, truncation, and URL
  normalization helpers.
- `src/maya_agent/instructions.py`: prompt loading and language directive.
- `src/maya_agent/latency.py`: turn latency logging from session events.
- `prompts/maya.md`: editable persona, resolved through
  `MAYA_PROMPT_PATH` (default `prompts/maya.md`).

## Invariants

- No OpenAI key is required. `livekit-plugins-openai` is the transport for DeepSeek.
- DeepSeek thinking is disabled for latency.
- Web search/extract uses Tavily. `TAVILY_API_KEY` is optional; without it the
  clients use keyless mode. Search results and page content are untrusted data.
- Weather/forecast uses Open-Meteo; market/stock uses Yahoo Finance; Wikipedia
  uses MediaWiki. None needs a key.
- `MAYA_TIMEZONE` must be a valid IANA timezone.
- `calculate` uses an AST allowlist, never `eval`.
- `.env` is gitignored and must stay out of commits.
- Tests must not load `.env`, download models, or make network calls. Inject fake
  request functions or fake clients for tool tests.
- Keep one concrete adapter per capability. Add a factory/union only when a second
  adapter exists.

## Adding a provider later

1. Add a settings group in `config.py`.
2. Add a builder module with the same shape as the current adapter. For web
   search, implement `WebSearchClient`; for extraction, implement
   `WebExtractClient`; for data APIs, inject the request function for tests.
3. Wire the builder in `tools/__init__.py` (and add a selector only if there are
   now two).
4. Update `.env.example`, README, and tests.
