# Polaris — Documentação Técnica

> Assistente de voz local: **Pipecat** (voz, STT, TTS, streaming) + **Hermes Agent** (cérebro agêntico).
> Especificação original: `docs/Implementação de agente de voz com Pipecat + Hermes Agent.md`.
> Versões validadas em 13/08/2026: **Pipecat 1.7.0** · **Hermes Agent 0.20.1** · Python 3.13 (uv) · pytest 9.1.1 · respx 0.23.1.

---

## 1. Visão geral

Polaris é **a ponte** entre voz e agente. O Pipecat cuida de tudo que é áudio/orquestração em tempo real; o Hermes é o agente (LLM, tools, terminal, browser, memória, skills) e roda **em processo separado**, exposto em `http://127.0.0.1:8642/v1`. Nada é duplicado entre os dois.

```
Você  ──fala──▶  PIPECAT (processo 1)                HERMES AGENT (processo 2)
                  ├─ captura de áudio (mic)             ┌─ LLM + reasoning
                  ├─ VAD / turn detection               ├─ Tools / Terminal / Browser
                  ├─ STT (Whisper local, pt-BR)         ├─ Memory / Skills / Subagents
                  ├─ sessão de voz                  ──▶ └─ API server (OpenAI-compatível)
                  │      streaming SSE ◀────────────────┘
                  ├─ chunks → LLMTextFrame
                  ├─ TTS (Kokoro local / ElevenLabs nuvem, incremental)
                  └─ reprodução (speaker)
```

### Decisões de projeto (da spec)

| Decisão | Motivo |
|---|---|
| `HermesLLMService` customizado em vez do `OpenAILLMService` nativo | O SSE do Hermes emite `event: hermes.tool.progress` — payload que o SDK OpenAI não consegue parsear. Validado por spike. |
| Sessão única no Hermes (`X-Hermes-Session-Id`) | Spec §8: não manter duas fontes de verdade para histórico. Só a nova mensagem do usuário vai na rede por turno. |
| Eventos de ferramenta **logados, nunca falados** | Spec §15: eventos internos são observabilidade, não fala. |
| Agregação por sentença nativa do `TTSService` (`TextAggregationMode.SENTENCE`) | Spec §3/§5: TTS incremental sem enviar token por token. |
| Transport local (mic/speaker) com `pyaudio` | Spec §10: MVP sem web; transport isolado para futuro WebRTC/WebSocket. |
| Barge-in mínimo nativo | VAD no user aggregator + `InterruptionFrame` + fechamento da conexão HTTP (o Hermes cancela o turno no disconnect). |

---

## 2. Arquitetura

### 2.1 O pipeline Pipecat (ordem exata)

```
transport.input()        captura microfone (LocalAudioTransport)
    │ AudioRawFrame 16kHz
    ▼
WhisperSTTService        STT local (faster-whisper); emite TranscriptionFrame
    ▼
LLMUserAggregator        VAD (Silero) + turn detection; junta a fala do usuário
    │                       e emite LLMContextFrame quando o turno termina
    ▼
HermesLLMService         POST /v1/chat/completions (streaming SSE via httpx)
    │                       emite LLMFullResponseStartFrame → LLMTextFrame* → LLMFullResponseEndFrame
    ▼
KokoroTTSService         TTS local (ou ElevenLabsTTSService na nuvem, via TTS_PROVIDER);
    │                       agrega por sentença e sintetiza incrementalmente
    │
    ▼
transport.output()       reprodução no speaker
    ▼
LLMAssistantAggregator   registra a resposta no contexto (não reenviada ao Hermes)
```

A ordem vem do exemplo oficial do Pipecat (`06a-voice-agent-local.py`) e da spec §13.

### 2.2 Processos

| Processo | Comando | Papel |
|---|---|---|
| Hermes Agent | `hermes gateway` | API server em `127.0.0.1:8642` (auth: `Authorization: Bearer <API_SERVER_KEY>`) |
| Polaris | `uv run python app.py` | Pipeline de voz completo |

### 2.3 Fluxo de um turno

```
[Usuário fala]  → VAD detecta início/fim do turno
               → Whisper transcreve ("STT final transcript")
               → user aggregator monta LLMContextFrame
               → HermesLLMService:
                    1. log "Hermes request started" (+ métricas de início)
                    2. POST {base}/chat/completions
                       body:  {"model": "...", "messages": [nova msg user], "stream": true}
                       headers: Authorization + X-Hermes-Session-Id (a partir do 2º turno)
                    3. captura o X-Hermes-Session-Id ecoado na resposta
                    4. stream SSE:
                       - delta.content        → LLMTextFrame (flui p/ TTS na hora)
                       - hermes.tool.progress → log "Hermes tool activity" (NUNCA vira fala)
                       - [DONE]              → encerra
                    5. log "Hermes response completed" + métricas (ttft, total)
               → TTS agrega por sentença e fala enquanto o Hermes ainda gera
               → assistant aggregator registra a resposta
```

---

## 3. Estrutura do projeto

```
polaris/
├── app.py                      # entrypoint: config → health check → runner
├── pyproject.toml              # deps: pipecat-ai[kokoro,local,whisper,elevenlabs]>=1.4,<2 + libs NVIDIA CUDA 12 + dev
├── requirements.txt            # espelha o pyproject p/ instalação de primeira execução
├── polaris.sh                  # sobe hermes gateway + agente (exporta LD_LIBRARY_PATH das libs CUDA)
├── README.md                   # visão do usuário (instalação, execução, troubleshooting)
├── .env.example                # template de configuração (spec §12)
├── .gitignore                  # .env, .venv, caches
├── config/
│   └── settings.py             # Settings imutável + load_settings() com validação
├── pipeline/
│   ├── hermes.py               # ponte: parser SSE, HermesSessionManager, HermesLLMService
│   └── voice_pipeline.py       # build_services/build_pipeline/run_voice_agent
├── utils/
│   └── logging.py              # setup_logging(), log_metric(), LatencyTimer
├── tests/                      # 32 testes (ver §7)
│   ├── conftest.py             # fakes e helpers (make_settings, make_service, sse, chunk)
│   ├── test_config.py          # spec §19.1 — configuração
│   ├── test_pipeline.py        # spec §19.2 — criação do pipeline
│   ├── test_sse_parser.py      # spec §19.3 — parsing SSE
│   ├── test_frame_conversion.py# spec §19.4 — chunks → frames + payload
│   ├── test_done.py            # spec §19.5 — [DONE]
│   ├── test_http_error.py      # spec §19.6 — erros HTTP
│   ├── test_session.py         # spec §19.7 — sessão
│   └── test_interruption.py    # spec §19.8 — interrupção/cancelamento
└── docs/
    ├── Implementação de agente de voz com Pipecat + Hermes Agent.md   # spec
    └── polaris-documentacao.md  # este documento
```

---

## 4. Componentes em detalhe

### 4.1 `app.py`

- `main()`: carrega `.env` → `load_settings()` → `setup_logging()` → **health check** do Hermes (`GET {base}/health`, timeout 3 s) → `run_voice_agent()`.
- Hermes offline → log com instruções acionáveis (`hermes gateway`, `API_SERVER_ENABLED`, `API_SERVER_KEY`) e `exit 1`.
- `KeyboardInterrupt` → log de shutdown e exit 0.

### 4.2 `config/settings.py`

Dataclass `@dataclass(frozen=True)` `Settings` + `load_settings()` (via `python-dotenv`, `override=True`).

Validações embutidas:
- `HERMES_API_KEY` vazio → `ValueError` (fail-fast).
- `TTS_PROVIDER` fora de `kokoro`/`elevenlabs` → `ValueError`.
- `TTS_PROVIDER=elevenlabs` exige `ELEVENLABS_API_KEY` e `ELEVENLABS_VOICE_ID` (fail-fast — o serviço do pipecat só valida a chave no handshake do WebSocket).
- `STT_LANGUAGE` vazio → `None` (auto-detecção do Whisper).
- `HERMES_SESSION_ID` vazio → gera `voice-session-<uuid>`.

Tabela completa de variáveis na §6.

### 4.3 `pipeline/hermes.py` — a ponte (coração do sistema)

Três camadas testáveis de forma independente:

**a) Parser SSE puro** (sem I/O):

| Função | Comportamento |
|---|---|
| `parse_sse_lines(lines)` | Async generator que agrupa `event:`/`data:` em frames; aceita fonte **síncrona ou assíncrona** de linhas; ignora keepalive (`: ...`) e `id:`/`retry:`; faz flush do último frame sem linha em branco |
| `parse_chat_chunk(chunk)` | `[DONE]` → `done=True`; `event: hermes.tool.progress` → `tool_progress=dict` (sem texto!); `chat.completion.chunk` → `text_delta` + `finish_reason`; JSON inválido → chunk vazio (tolerante, nunca levanta) |

**b) `HermesSessionManager`** — sessão única (spec §8):

```
turno 1:  POST sem X-Hermes-Session-Id
          ← Hermes cria sessão e ecoa "X-Hermes-Session-Id: api-<id>"
          → set_session_id_from_response() captura o id
turno 2+: POST com X-Hermes-Session-Id: api-<id>   (histórico fica no Hermes)
```

Métodos: `header_value()`, `set_session_id_from_response(header)`, `current_hermes_session_id()`, propriedade `app_session_id`.

**c) `HermesLLMService(LLMService)`**:

```python
HermesLLMService(
    base_url="http://127.0.0.1:8642/v1",
    api_key="...",                  # = API_SERVER_KEY do Hermes
    model="hermes-agent",
    session_manager=HermesSessionManager("voice-session-<uuid>"),
    connect_timeout_secs=10.0,
)
```

- `process_frame()` espelha o `BaseOpenAILLMService` do Pipecat: no `LLMContextFrame`, envolve a inferência com `LLMFullResponseStartFrame` → `_process_context()` → `LLMFullResponseEndFrame` (sempre, via `finally` — inclusive em erro e cancelamento). Demais frames passam adiante.
- `_process_context()`:
  - extrai **apenas a última mensagem user** do `LLMContext` (`_extract_user_message`; histórico vive na sessão do Hermes);
  - faz `POST {base}/chat/completions` com `httpx.AsyncClient` (`stream=True`), timeouts: `connect=10s`, `read=None` (turno agentivo pode durar minutos);
  - status ≠ 200 → log + `push_error(ErrorFrame)` e retorna (turno fecha no `finally`);
  - itera o SSE: primeiro `delta.content` registra **TTFT** (`stop_ttfb_metrics` + `log_metric("hermes_ttft", ...)`); tool progress só loga; `[DONE]` encerra;
  - loga `hermes_total` no `finally`.
- Cancelamento (barge-in): o pipeline cancela a task em execução → `CancelledError` propaga pelo `finally` (que fecha o client httpx) → **fechar a conexão é como o Hermes cancela o turno agentivo** (comportamento confirmado no código-fonte do Hermes: "SSE client disconnected; interrupted agent task").

Formato SSE real validado por spike (Hermes 0.20.1):

```
data: {"id":"chatcmpl-...","object":"chat.completion.chunk",...,"choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}
data: {"id":"...","choices":[{"index":0,"delta":{"content":"test"},"finish_reason":null}]}
event: hermes.tool.progress
data: {"tool":"terminal","label":"ls -A /tmp + 1 command","toolCallId":"call_...","status":"running"}
data: {"id":"...","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":16793,...}}
data: [DONE]
```

### 4.4 `pipeline/voice_pipeline.py`

- `VOICE_AGENT_SAMPLE_RATE = 24000` — taxa nativa do Kokoro (evita resample).
- `build_transport(settings)` — `LocalAudioTransport` (import **lazy** por causa do pyaudio) com `audio_in_enabled`/`audio_out_enabled` e índices de dispositivo opcionais.
- `build_services(settings, *, transport, stt, llm, tts, context, session_manager)` — todos os componentes **injetáveis** (testes passam fakes sem carregar modelos):
  - `WhisperSTTService(device=..., compute_type=..., settings=WhisperSTTService.Settings(model=..., language=..., no_speech_prob=0.4))` — usa `settings=` porque `model=`/`language=`/`no_speech_prob=` no construtor estão **deprecados** desde 1.7;
  - `_build_tts_service(settings)` — único ponto de troca de TTS: `TTS_PROVIDER=kokoro` → `KokoroTTSService(settings=KokoroTTSService.Settings(voice=..., language=...), sample_rate=24000)`; `TTS_PROVIDER=elevenlabs` → `ElevenLabsTTSService(api_key=..., settings=ElevenLabsTTSService.Settings(voice=..., model=..., language=...), sample_rate=24000)` (WebSocket `multi-stream-input`, streaming incremental; import lazy). `push_start_frame`/`push_stop_frames` já são defaults; agregação `SENTENCE` é default do `TTSService`;
  - `_tts_language()`: `pt`/`pt-br` → `Language.PT_BR`; qualquer outra string vira `Language(value)`. No ElevenLabs vira `language_code=pt` na URL do WS (modelos multilingual).
- `build_pipeline(..., vad_analyzer, wake_word_enabled, wake_phrases, wake_timeout)` — com wake word habilitado, monta `LLMUserAggregatorParams(user_turn_strategies=UserTurnStrategies(start=[WakePhraseUserTurnStartStrategy(phrases=..., timeout=...), *default_user_turn_start_strategies()]))`: a strategy fica **primeira** e bloqueia turnos enquanto dorme (padrão documentado do pipecat; `stop` fica `None` → defaults preservados). `_expand_wake_phrases()` gera variantes `polaris↔polares` (o Whisper transcreve "polares") e minúsculas (matching é case-insensitive); handlers `on_wake_phrase_detected`/`on_wake_phrase_timeout` logam em INFO.
- `build_pipeline(transport, stt, llm, tts, context, *, vad_analyzer=_UNSET)` — monta a ordem da §2.1; `vad_analyzer=None` nos testes evita carregar o modelo Silero (que é bundled no wheel, sem download).
- `run_voice_agent(settings, ...)` — `PipelineWorker(pipeline, params=PipelineParams(enable_metrics=True, enable_usage_metrics=True), idle_timeout_secs=None, conversation_id=<app session>)` + `WorkerRunner` + `queue_frames([LLMRunFrame()])` + `await runner.run()`.
  - `idle_timeout_secs=None` é **essencial**: o default (300 s) mataria o Polaris após 5 min de silêncio.
  - `PipelineTask`/`PipelineTaskParams` estão deprecados desde 1.3.0 — usamos `PipelineWorker`.

### 4.5 `utils/logging.py`

- `setup_logging(level)` — loguru no stderr.
- `log_metric(name, value_ms, **tags)` — linha padronizada `METRIC <name> value_ms=<x> tag=...`.
- `LatencyTimer` — context manager que mede e loga uma métrica.

Métricas emitidas hoje: `hermes_ttft` (time-to-first-token) e `hermes_total` por turno. Métricas do Pipecat (STT/TTS/processamento) ficam disponíveis com `enable_metrics=True` via frames internos.

### 4.6 `tests/`

Ver §7.

---

## 5. Fluxos principais

### 5.1 Turno completo (frames reais observados no E2E)

```
23:26:55 Hermes request started (session=new, message='Olá!')
23:26:55 METRIC hermes_total value_ms=26.4        ← cancelado por barge-in (sem [DONE])
23:26:58 Hermes request started (session=api-164a..., message='em você.')
23:27:01 METRIC hermes_ttft value_ms=3021.2 → Hermes response started
23:27:01 Hermes response completed (finish_reason=None)
```

### 5.2 Streaming e TTS incremental

Chunks de texto chegam como `LLMTextFrame`s; o `TTSService` (com `TextAggregationMode.SENTENCE` default) acumula até o fim de uma sentença e então sintetiza — a voz começa **antes** do fim da resposta do Hermes. O flush final acontece no `LLMFullResponseEndFrame`.

### 5.3 Sessão

Ver §4.3b. Evidência do E2E: correção de contexto ("Eu quis dizer 21 Pilots" após pedir "Twinian Palates") foi entendida — histórico preservado pelo Hermes, sem reenvio.

### 5.4 Interrupção / barge-in

```
VAD (no user aggregator) detecta fala durante resposta do bot
  → broadcast de InterruptionFrame
  → FrameProcessor cancela a task da inferência em andamento
  → finally do HermesLLMService fecha o stream HTTP
  → Hermes detecta disconnect e interrompe o turno agentivo (reaper no source)
  → nova fala é processada como novo turno
```

Observação real do E2E: turnos cancelados fecham **sem** `[DONE]` (o log mostra só `hermes_total`) — comportamento esperado.

### 5.5 Erros HTTP

Status ≠ 200 → log do corpo (truncado em 300 chars) + `ErrorFrame` upstream (via `push_error`) + turno fechado com `LLMFullResponseEndFrame`. Coberto por testes para 401 e 500.

---

## 6. Configuração (`.env`)

| Variável | Default | Efeito |
|---|---|---|
| `HERMES_BASE_URL` | `http://127.0.0.1:8642/v1` | Endpoint do API server do Hermes |
| `HERMES_API_KEY` | *(obrigatória)* | Deve ser igual a `API_SERVER_KEY` de `~/.hermes/.env` |
| `HERMES_MODEL` | `hermes-agent` | Modelo anunciado no `/v1/models` |
| `HERMES_SESSION_ID` | *(gerado: `voice-session-<uuid>`)* | Id da conversa no lado Polaris |
| `STT_MODEL` | `small` | `tiny`/`base`/`small`/`medium`/`large` (faster-whisper) |
| `STT_DEVICE` | `cpu` | `cpu`/`cuda`/`auto` |
| `STT_COMPUTE_TYPE` | `int8` | Precisão do ctranslate2 |
| `STT_LANGUAGE` | `pt` | Vazio = auto-detecção |
| `TTS_PROVIDER` | `kokoro` | `kokoro` (local) ou `elevenlabs` (nuvem) |
| `TTS_LANGUAGE` | `pt` | `pt`/`pt-br` → `Language.PT_BR` |
| `TTS_VOICE` | `pf_dora` | Vozes pt-BR: `pf_dora`, `pm_alex`, `pm_santa` |
| `ELEVENLABS_API_KEY` | *(vazio)* | Obrigatória com `TTS_PROVIDER=elevenlabs` |
| `ELEVENLABS_VOICE_ID` | *(vazio)* | Obrigatória com `TTS_PROVIDER=elevenlabs` (premade ou clonada) |
| `ELEVENLABS_MODEL_ID` | `eleven_flash_v2_5` | Realtime/multilingual; sobrescreva se quiser outro modelo |
| `WAKE_WORD_ENABLED` | `false` | `true` exige wake phrase (transcrição) antes de cada conversa |
| `WAKE_WORD_PHRASES` | `E aí, Polaris;Ei, Polaris;Polaris, tá aí?` | Lista separada por `;` (vírgulas ficam dentro das frases) |
| `WAKE_WORD_TIMEOUT` | `10` | Segundos de inatividade até voltar a dormir |
| `LOG_LEVEL` | `INFO` | `DEBUG` mostra detalhes do Pipecat |
| `AUDIO_IN_DEVICE` / `AUDIO_OUT_DEVICE` | *(vazio)* | Índices PyAudio; vazio = padrão do sistema |

---

## 7. Testes

### Como rodar

```bash
uv run pytest -q          # suíte completa (offline, sem Hermes e sem modelos)
uvx ruff check .          # lint
```

### Estratégia

- **Hermes fake**: `respx` mocka o transporte do `httpx.AsyncClient` — nenhum servidor real. Atenção: no respx 0.23 a classe é **`respx.MockResponse`** (`respx.Response` foi removida).
- **Harness oficial do Pipecat**: `run_test()` de `pipecat.tests.utils` monta `Pipeline([source, processor, sink])` com `PipelineWorker` + `WorkerRunner` reais e captura frames downstream/upstream (incluindo `ErrorFrame`).
- **Frames esperados**: toda execução do `HermesLLMService` emite `LLMServiceMetadataFrame` (no start) + `LLMFullResponseStartFrame` + `LLMFullResponseEndFrame`; ajuste as listas de expectativa se mudar o serviço.
- **Interrupção**: stream fake que estala (`httpx.AsyncByteStream` custom), `InterruptionFrame` enviado do source, e asserts de que o turno fecha com `LLMFullResponseEndFrame`.
- Fixture `no_dotenv` (autouse) impede que um `.env` local contamine os testes.

### Mapeamento spec §19 → arquivos

| Item | Arquivo | O que cobre |
|---|---|---|
| 1. Configuração | `test_config.py` | env vars, defaults, `voice-session-<uuid>`, erros de validação |
| 2. Criação do pipeline | `test_pipeline.py` | ordem do `Pipeline`, tipos dos aggregators, VAD default |
| 3. Parsing SSE | `test_sse_parser.py` | frames, keepalive, multi-data, flush, fonte async |
| 4. Chunks → frames | `test_frame_conversion.py` | `LLMTextFrame`s na ordem; tool progress filtrado; payload do request; só última msg user |
| 5. `[DONE]` | `test_done.py` | stream para no `[DONE]`; dados após são ignorados; turno sem texto fecha limpo |
| 6. Erro HTTP | `test_http_error.py` | 401/500 → `ErrorFrame` upstream + turno fechado, sem crash |
| 7. Sessão | `test_session.py` | unit do `HermesSessionManager` + fluxo 1º/2º request com header |
| 8. Interrupção | `test_interruption.py` | cancelamento da inferência em voo + turno fechado |

### Como adicionar um teste

```python
# tests/test_novo.py
import respx
from pipecat.frames.frames import LLMContextFrame
from pipecat.tests.utils import run_test
from conftest import HERMES_COMPLETIONS_URL, chunk, make_context, make_service, sse

@respx.mock
async def test_minha_mudanca():
    respx.post(HERMES_COMPLETIONS_URL).mock(
        return_value=respx.MockResponse(
            200, content=sse((None, chunk("resposta")), (None, "[DONE]"))
        )
    )
    down, _up = await run_test(
        make_service(),
        frames_to_send=[LLMContextFrame(context=make_context("pergunta"))],
    )
    assert any(f.text == "resposta" for f in down if isinstance(f, LLMTextFrame))
```

---

## 8. Guia de alterações em pontos-chave

### Voz do TTS
Kokoro: `.env` → `TTS_VOICE=pm_alex` (ou `pf_dora`/`pm_santa`). Outras vozes do Kokoro funcionam trocando também `TTS_LANGUAGE`.

ElevenLabs: `.env` → `TTS_PROVIDER=elevenlabs` + `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID` (voz premade ou clonada; o id é um hash tipo `21m00Tcm4TlvDq8ikWAM`).

### Idioma
- STT: `STT_LANGUAGE=pt` fixo, ou vazio para auto-detecção. O mapeamento Whisper é feito por `Language(settings.stt_language)` em `voice_pipeline.build_services`.
- TTS: `_tts_language()` em `pipeline/voice_pipeline.py` — adicione mapeamentos ali (ex.: `"en"` → `Language.EN_US`).

### Sensibilidade do VAD / fim de turno
Em `pipeline/voice_pipeline.py`, `build_pipeline`:

```python
from pipecat.audio.vad.vad_analyzer import VADParams

user_params=LLMUserAggregatorParams(
    vad_analyzer=SileroVADAnalyzer(
        params=VADParams(confidence=0.7, start_secs=0.2, stop_secs=0.4, min_volume=0.6)
    )
)
```

- `stop_secs` maior = espera mais silêncio para encerrar o turno (menos cortes);
- `min_volume` maior = ignora ruído ambiente (evita barge-in acidental);
- `audio_idle_timeout`/`user_turn_stop_timeout` também existem em `LLMUserAggregatorParams` (defaults 1.0/5.0).

### Modelo/GPU do Whisper
`STT_MODEL`, `STT_DEVICE`, `STT_COMPUTE_TYPE` no `.env`. Para CPU fraca: `STT_MODEL=base`. Em `voice_pipeline.build_services` o `no_speech_prob=0.4` (filtra alucinações de fala em silêncio).

Com `STT_DEVICE=cuda`, o ctranslate2 precisa das libs CUDA runtime — instaladas via pip (`nvidia-cublas-cu12`/`nvidia-cudnn-cu12`/`nvidia-cuda-runtime-cu12`) e expostas pelo `./polaris.sh` via `LD_LIBRARY_PATH` (sem isso: `Library libcublas.so.12 is not found`).

### Wake word
Ligada por `WAKE_WORD_ENABLED=true` no `.env` (por transcrição, sem modelo extra). Enquanto dorme, nenhuma fala chega ao Hermes (o `WakePhraseUserTurnStartStrategy` retorna `STOP` e reseta a agregação em transcrições sem match); a frase detectada inicia o turno normalmente — e o próprio texto dela vira o input (dizer só "E aí, Polaris" gera uma resposta de saudação). Após `WAKE_WORD_TIMEOUT` s de inatividade, volta a dormir (evento `on_wake_phrase_timeout`). Com wake ativo, `run_voice_agent` **não** enfileira o `LLMRunFrame` de kickstart (senão o Hermes falaria no boot). Frases: separadas por `;`, case-insensitive, e as grafias "Polaris"/"Polares" são equivalentes automaticamente (`_expand_wake_phrases`). Atenção: acentos importam ("aí" ≠ "ai") — se o Whisper transcrever sem acento, adicione a variante à lista.

### Agregação do TTS
`TextAggregationMode.SENTENCE` é o default. Para mudar: passe `text_aggregation_mode=TextAggregationMode.TOKEN` no construtor do serviço em `_build_tts_service()` (fala por token — mais responsivo, mais cortes) ou `NONE` (fala só no fim). Import: `pipecat.services.tts_service.TextAggregationMode`.

### Porta/URL do Hermes
Hermes: `API_SERVER_PORT` em `~/.hermes/.env`. Polaris: `HERMES_BASE_URL` no `.env`. O health check do `app.py` usa `{base_url}/health`.

### Novos eventos SSE do Hermes
Tudo passa por `parse_chat_chunk()` em `pipeline/hermes.py` — chunks desconhecidos são descartados de forma tolerante. Para tratar um evento novo (ex.: `hermes.thinking`), adicione um branch em `parse_chat_chunk` e decida em `_process_context` se vira `LLMTextFrame`, log ou nada.

### Falar status de ferramenta (futuro, decisão explícita — spec §15)
Hoje `tool_progress` é só log. Para falar algo ("Vou verificar isso..."), gere texto na **camada de voz**, em `_process_context`, ex.:

```python
if chunk.tool_progress and chunk.tool_progress.get("status") == "running":
    await self._push_llm_text("Só um instante...")
```

Nunca leia o payload do evento diretamente no TTS.

### Timeouts
`connect_timeout_secs=10.0` no construtor do `HermesLLMService`. O read timeout é `None` de propósito (turnos com ferramenta demoram); o keepalive do Hermes (30 s) mantém a conexão viva. Para limitar turnos, use `asyncio.wait_for` em `_process_context` — mas prefira o barge-in como mecanismo de cancelamento.

### Trocar o transport (WebRTC/WebSocket futuro)
O transport é isolado em `build_transport()` e injetado em `run_voice_agent(settings, transport=...)`. Basta implementar outro transport do Pipecat (ex.: `DailyTransport`, `WebsocketServerTransport`) e trocar a factory — pipeline, serviços e ponte Hermes não mudam.

### System prompt / personalidade
**Não há system prompt no Polaris** — de propósito: o Hermes é a autoridade agêntica (spec §24). Ajustes de personalidade devem ser feitos no profile/config do Hermes (`~/.hermes/`), não no Pipecat. Evite adicionar `context.add_message({"role": "developer", ...})` — a mensagem entraria em duplicidade com o prompt do agente e poluiria a sessão.

### Trocar STT/TTS por outro serviço
`build_services()` é o único lugar: substitua `WhisperSTTService` por qualquer `SegmentedSTTService` do Pipecat e o conteúdo de `_build_tts_service()` por outro `TTSService` (ou adicione um branch novo no `TTS_PROVIDER`). O restante do pipeline (agregadores, ponte, runner) permanece.

### Atualizar o Pipecat
Pin atual: `pipecat-ai>=1.4.0,<2.0` (instalado 1.7.0). O Pipecat muda rápido — antes de subir versão: rode `uv run pytest -q`, confira `uv run python -c "import app"` e revise deprecações no changelog (já pegamos `PipelineTask`, `WhisperSTTService(model=...)`, `KokoroTTSService(voice_id=...)`).

---

## 9. Referência de APIs validadas (agosto/2026)

### Pipecat 1.7.0 (instalado — conferido no código do pacote)

| Componente | Import | Notas |
|---|---|---|
| Transport local | `pipecat.transports.local.audio` → `LocalAudioTransport(LocalAudioTransportParams(...))` | Extra `[local]` = `pyaudio` (compila da fonte; precisa `portaudio19-dev`) |
| VAD | `pipecat.audio.vad.silero` → `SileroVADAnalyzer(params=VADParams(...))` | Modelo ONNX **bundled** no wheel; VAD vai no `LLMUserAggregatorParams`, não no STT |
| STT | `pipecat.services.whisper.stt` → `WhisperSTTService` | Usar `settings=WhisperSTTService.Settings(model=..., language=..., no_speech_prob=...)`; `device=`/`compute_type=` são args do construtor |
| TTS | `pipecat.services.kokoro.tts` → `KokoroTTSService` | `settings=KokoroTTSService.Settings(voice=..., language=...)`; `sample_rate=24000`; agregação `SENTENCE` default do `TTSService`; modelos em `~/.cache/pipecat/kokoro-onnx/` |
| TTS (alternativo) | `pipecat.services.elevenlabs.tts` → `ElevenLabsTTSService` | `api_key=` (kwarg obrigatório) + `settings=ElevenLabsTTSService.Settings(voice=<voice_id>, model=..., language=...)`; WebSocket `multi-stream-input` com `output_format=pcm_24000`; `auto_mode=true` com agregação `SENTENCE`; não usa `voice_id=`/`model=` diretos (deprecados); chave só é validada no handshake |
| Context | `pipecat.processors.aggregators.llm_context` → `LLMContext` + `pipecat.processors.aggregators.llm_response_universal` → `LLMContextAggregatorPair` | `LLMStandardMessage` é alias de `ChatCompletionMessageParam` do OpenAI — mensagens já são compatíveis |
| Runner | `pipecat.pipeline.worker` → `PipelineWorker` + `pipecat.workers.runner` → `WorkerRunner` | `PipelineTask` deprecado desde 1.3.0 |
| Frames | `pipecat.frames.frames` → `LLMRunFrame`, `LLMContextFrame`, `LLMTextFrame`, `LLMFullResponseStart/EndFrame`, `InterruptionFrame`, `ErrorFrame`, `LLMServiceMetadataFrame` | `LLMServiceMetadataFrame` é emitido pelo serviço no start (presente nos testes) |
| Linguagem | `pipecat.transcriptions.language` → `Language` (StrEnum) | `Language.PT`, `Language.PT_BR` |
| Interrupção | `InterruptionFrame` chega pelo caminho de system frames e cancela a task da inferência | `broadcast_interruption()` é o mecanismo do VADController |

### Hermes Agent 0.20.1 (validado no código-fonte instalado + spike ao vivo)

| Item | Detalhe |
|---|---|
| Comando | `hermes gateway` (API server sobe junto; config em `~/.hermes/.env`) |
| Config | `API_SERVER_ENABLED=true`, `API_SERVER_KEY=<token>` (obrigatória), `API_SERVER_PORT=8642`, `API_SERVER_HOST=127.0.0.1`, `API_SERVER_MODEL_NAME` |
| Auth | `Authorization: Bearer <API_SERVER_KEY>` |
| Endpoints | `GET /v1/health`, `GET /v1/models`, `GET /v1/capabilities`, `POST /v1/chat/completions` (SSE) |
| SSE | `event: <nome>\ndata: <json>\n\n`; chunks `chat.completion.chunk` com `delta.content`; keepalive `: keepalive` (30 s); fim = `data: [DONE]`; chunk final com `finish_reason` (`stop`/`length`/`error`) + `usage` |
| Tool progress | `event: hermes.tool.progress`, payload `{"tool", "label", "emoji", "toolCallId", "status": "running"\|"completed"}` — **não** vaza para `delta.content` |
| Sessão | Stateless por padrão; com `X-Hermes-Session-Id` carrega a sessão do SessionDB e anexa as mensagens; id **ecoado no header da resposta**; `X-Hermes-Session-Key` (opcional) escopa memória de longo prazo |
| Cancelamento | Sem endpoint para chat completions — fechar a conexão HTTP interrompe o turno ("SSE client disconnected; interrupted agent task") |

---

## 10. Operação

### Comandos

```bash
# Hermes (terminal 1)
hermes gateway                 # API server em http://127.0.0.1:8642

# Polaris (terminal 2)
uv run python app.py           # fale no microfone; Ctrl+C para sair

# Qualidade
uv run pytest -q               # 32 testes, offline
uvx ruff check .               # lint
```

### Primeiros downloads (uma vez)

| Recurso | Onde |
|---|---|
| Modelo Whisper (`small` ≈ 465 MB) | cache do ctranslate2 (`~/.cache/huggingface/`) — baixa no 1º turno |
| Kokoro (`kokoro-v1.0.onnx` ≈ 325 MB + vozes ≈ 28 MB) | `~/.cache/pipecat/kokoro-onnx/` — baixa no start do TTS |

**Cuidado**: se o processo for morto no meio do download do Kokoro, o arquivo fica corrompido (`INVALID_PROTOBUF` no start). Solução: apagar os arquivos de `~/.cache/pipecat/kokoro-onnx/` e rodar de novo.

### Troubleshooting rápido

| Sintoma | Solução |
|---|---|
| `Hermes API server is offline` | `hermes gateway` + `API_SERVER_ENABLED=true` em `~/.hermes/.env` |
| HTTP 401 | `HERMES_API_KEY` (projeto) deve ser igual a `API_SERVER_KEY` (`~/.hermes/.env`) |
| Porta ocupada | `API_SERVER_PORT` no Hermes + `HERMES_BASE_URL` no projeto |
| Sem áudio/microfone | `AUDIO_IN_DEVICE`/`AUDIO_OUT_DEVICE` (índices PyAudio) |
| Ruído de ALSA/Jack no log | Inofensivo — é o PortAudio sondando dispositivos |
| Latência alta | `STT_MODEL=base`, `STT_COMPUTE_TYPE=int8`, `stop_secs` menor no VAD |
| Warning `Language pt-BR not verified` | Inofensivo — Kokoro usa o código base `pt` |
| Barge-in trunca transcrição | Limitação do `STT_MODEL=small`; use `medium`/`large-v3-turbo` |

### Limitações conhecidas (v1)

- STT por turno (não streaming contínuo de transcrição) — spec §23 prevê streaming STT no futuro.
- Barge-in fecha o stream sem `[DONE]` (esperado; o Hermes reaproveita o turno no disconnect).
- Sem wake word, sem web/WebRTC, sem multiusuário (fora do escopo da v1 — spec §22).
- Histórico/memória: 100% no Hermes; o Polaris não persiste nada além da sessão em memória (o id da sessão do Hermes é perdido ao reiniciar o Polaris — um `HERMES_SESSION_ID` fixo no `.env` é a forma de manter a mesma conversa entre execuções).
