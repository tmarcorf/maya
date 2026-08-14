# Polaris

Assistente de voz local controlado por **Pipecat** (voz, STT, TTS, streaming) e **Hermes Agent** (cérebro agêntico: LLM, tools, terminal, browser, memória). Polaris é a ponte entre os dois — você fala, o Hermes pensa e executa, e Polaris responde em voz, **sem esperar a resposta completa para começar a falar**.

## Arquitetura

```
Você  ──fala──▶  PIPECAT                      HERMES AGENT (processo separado)
                  ├─ captura de áudio (mic)     ┌─ LLM + reasoning
                  ├─ VAD / turn detection       ├─ Tools / Terminal / Browser
                  ├─ STT (Whisper, local)       ├─ Memory / Skills / Subagents
                  ├─ sessão de voz          ──▶ └─ http://127.0.0.1:8642/v1
                  │      streaming SSE ◀────────┘  (POST /v1/chat/completions)
                  ├─ chunks → LLMTextFrame
                  ├─ TTS (Kokoro local / ElevenLabs nuvem)
                  └─ reprodução (speaker)
```

Dois processos, uma divisão clara de responsabilidades:

- **Pipecat** cuida de: áudio, VAD, turn detection, STT, pipeline assíncrono, streaming, TTS, interrupções e métricas.
- **Hermes** cuida de: raciocínio, LLM, execução de ferramentas, terminal, browser, memória, skills e subagentes.

O Pipecat não duplica nada do Hermes — Polaris é essencialmente a ponte entre voz e agente.

### Streaming de ponta a ponta

O texto do Hermes chega por SSE e cada chunk vira um `LLMTextFrame`, que o Pipecat encaminha ao TTS (Kokoro ou ElevenLabs, via `TTS_PROVIDER`) com **agregação por sentença** (nativa do `TTSService`). O TTS começa assim que a primeira sentença está completa — não há espera pela resposta inteira.

### Sessão

A conversa é mantida **exclusivamente pelo Hermes**: a primeira requisição não envia `X-Hermes-Session-Id` (o Hermes cria uma sessão e ecoa o id no header da resposta); as seguintes reutilizam esse id. O histórico nunca é duplicado no Pipecat — a cada turno só a nova mensagem do usuário vai na rede. O id local da conversa é `voice-session-<uuid>`.

### Eventos de ferramenta

O Hermes emite `event: hermes.tool.progress` durante execuções de ferramenta. Polaris **registra esses eventos no log** (observabilidade) e **nunca** os envia ao TTS — você ouve apenas a resposta final do agente.

### Interrupção (barge-in)

Se você começar a falar enquanto o Polaris responde, o VAD do Pipecat dispara um `InterruptionFrame`, a inferência em andamento é cancelada e a conexão HTTP com o Hermes é fechada — o que faz o Hermes cancelar o turno agentivo. A nova fala então é processada normalmente.

## Pré-requisitos

- Python 3.11+ (gerenciado pelo uv)
- [uv](https://docs.astral.sh/uv/)
- **Linux**: `portaudio19-dev` (para compilar o PyAudio do transport local):
  ```bash
  sudo apt-get install -y portaudio19-dev
  ```
- Microfone e saída de áudio
- [Hermes Agent](https://github.com/NousResearch/hermes-agent) instalado (CLI `hermes`)

## Instalação

```bash
cd polaris
uv pip install -r requirements.txt      # cria/abastece o venv com todas as deps
                                        # (equivalente ao uv sync; inclui as libs CUDA)
cp .env.example .env                    # depois edite HERMES_API_KEY
```

Dependências: `pipecat-ai[whisper,kokoro,local,elevenlabs]`, `python-dotenv`, `loguru`, `httpx`, libs NVIDIA CUDA 12 (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`, `nvidia-cuda-runtime-cu12`) (dev: `pytest`, `pytest-asyncio`, `respx`).

Na primeira execução os modelos são baixados automaticamente:
- Whisper (faster-whisper) para o cache do ctranslate2;
- Kokoro (`kokoro-v1.0.onnx` + vozes) para `~/.cache/pipecat/kokoro-onnx/`.

## Hermes

Habilite o API server em `~/.hermes/.env`:

```env
API_SERVER_ENABLED=true
API_SERVER_KEY=uma-chave-local-qualquer
```

O gateway pode ser iniciado manualmente (o API server sobe junto) ou automaticamente pelo `./run.sh`:

```bash
hermes gateway
# [API Server] API server listening on http://127.0.0.1:8642
```

Teste rápido:

```bash
curl -N http://127.0.0.1:8642/v1/health
```

Use a mesma `API_SERVER_KEY` no `HERMES_API_KEY` do `.env` deste projeto. Não exponha o API server fora de 127.0.0.1.

## Execução

```bash
./run.sh
```

O `run.sh` faz tudo: sobe o `hermes gateway` (se ainda não estiver no ar — reutiliza um já rodando), espera o health check responder, ajusta o `LD_LIBRARY_PATH` para as libs CUDA instaladas via pip (o ctranslate2 do Whisper precisa delas quando `STT_DEVICE=cuda`) e então roda o agente. Ctrl+C encerra tudo — inclusive o gateway que ele subiu. Com `STT_DEVICE=cpu` você pode rodar `uv run python app.py` diretamente (com o Hermes já no ar).

Fale no microfone. O Polaris detecta o fim do turno, transcreve, envia ao Hermes e começa a responder enquanto a resposta ainda está sendo gerada. Ctrl+C para encerrar.

Para usar uma voz da ElevenLabs em vez do Kokoro, configure no `.env`:

```env
TTS_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=...   # chave da API
ELEVENLABS_VOICE_ID=...  # id da voz (premade ou clonada)
```

Exemplo de conversa:

> Você: "Que arquivos existem no meu projeto?"
> Polaris (via Hermes + terminal): "Encontrei os seguintes arquivos..."

## Testes

```bash
uv run pytest -q
```

A suíte cobre: configuração, criação do pipeline, parsing SSE, conversão de chunks em frames, `[DONE]`, erros HTTP, sessão e interrupção/cancelamento — tudo com um Hermes fake (respx), sem rede e sem modelos reais.

## Troubleshooting

| Sintoma | Solução |
|---|---|
| `Hermes API server is offline` | Rode `hermes gateway` e confira `API_SERVER_ENABLED=true` em `~/.hermes/.env` |
| HTTP 401 do Hermes | `HERMES_API_KEY` do `.env` precisa ser igual a `API_SERVER_KEY` de `~/.hermes/.env` |
| Porta 8642 ocupada | Mude `API_SERVER_PORT` em `~/.hermes/.env` e `HERMES_BASE_URL` no `.env` |
| Sem captura de áudio | Liste dispositivos e use `AUDIO_IN_DEVICE`/`AUDIO_OUT_DEVICE` (índices PyAudio) |
| Erro ao instalar (`portaudio.h`) | `sudo apt-get install -y portaudio19-dev` e rode `uv sync` de novo |
| Download do modelo Whisper lento | O primeiro turno baixa o modelo; use `STT_MODEL=base` para máquinas modestas |
| `Library libcublas.so.12 is not found` | Rode via `./run.sh` (expõe as libs CUDA do pip via `LD_LIBRARY_PATH`) ou use `STT_DEVICE=cpu` |
| Sem áudio do Kokoro | Confira `~/.cache/pipecat/kokoro-onnx/` (modelo + vozes); teste `TTS_VOICE=pm_alex` |
| Sem áudio do ElevenLabs | Confira rede, `ELEVENLABS_API_KEY`/`ELEVENLABS_VOICE_ID` e o modelo (`ELEVENLABS_MODEL_ID`) |
| Latência alta | `STT_MODEL=base` (ou `tiny`), `STT_COMPUTE_TYPE=int8`, e menos tempo de silêncio no VAD |
| Respostas truncadas/interrompidas | Confira microfone (o VAD pode estar interpretando ruído como barge-in) |

## Roadmap

- Wake word, barge-in avançado, streaming STT
- Transportes WebRTC/WebSocket (web e mobile) — a arquitetura já isola o transport
- Interface web e múltiplos usuários
- Observabilidade avançada (métricas end-to-end)

A spec original do projeto está em `docs/Implementação de agente de voz com Pipecat + Hermes Agent.md`.
