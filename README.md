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
                  ├─ TTS (Kokoro local / Qwen3-TTS local GPU / ElevenLabs nuvem)
                  └─ reprodução (speaker)
```

Dois processos, uma divisão clara de responsabilidades:

- **Pipecat** cuida de: áudio, VAD, turn detection, STT, pipeline assíncrono, streaming, TTS, interrupções e métricas.
- **Hermes** cuida de: raciocínio, LLM, execução de ferramentas, terminal, browser, memória, skills e subagentes.

O Pipecat não duplica nada do Hermes — Polaris é essencialmente a ponte entre voz e agente.

### Streaming de ponta a ponta

O texto do Hermes chega por SSE e cada chunk vira um `LLMTextFrame`, que o Pipecat encaminha ao TTS (Kokoro, Qwen3-TTS ou ElevenLabs, via `TTS_PROVIDER`) com **agregação por sentença** (nativa do `TTSService`). O TTS começa assim que a primeira sentença está completa — não há espera pela resposta inteira.

### Sessão

A conversa é mantida **exclusivamente pelo Hermes**: a primeira requisição não envia `X-Hermes-Session-Id` (o Hermes cria uma sessão e ecoa o id no header da resposta); as seguintes reutilizam esse id. O histórico nunca é duplicado no Pipecat — a cada turno só a nova mensagem do usuário vai na rede. O id local da conversa é `voice-session-<uuid>`.

### Eventos de ferramenta

O Hermes emite `event: hermes.tool.progress` durante execuções de ferramenta. Polaris **registra esses eventos no log** (observabilidade) e **nunca** fala o payload bruto — mas, para tarefas longas não virarem silêncio, fala **frases curadas em pt-BR** ("Hmm, deixa eu ver", "vou mexer no terminal", "só mais um instante") controladas pelos knobs `FILLER_*` do `.env` (ligadas por padrão; desligue com `FILLER_ENABLED=false`).

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
- **GPU NVIDIA com CUDA** (obrigatória apenas para `TTS_PROVIDER=qwen3`; Kokoro e ElevenLabs funcionam sem)
- [Hermes Agent](https://github.com/NousResearch/hermes-agent) instalado (CLI `hermes`)

## Instalação

```bash
cd polaris
uv pip install -r requirements.txt      # cria/abastece o venv com todas as deps
                                        # (equivalente ao uv sync; inclui as libs CUDA)
cp .env.example .env                    # depois edite HERMES_API_KEY
```

Dependências: `pipecat-ai[whisper,kokoro,local,elevenlabs]`, `python-dotenv`, `loguru`, `httpx`, libs NVIDIA CUDA 12 (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`, `nvidia-cuda-runtime-cu12`), `qwen-tts` (puxa torch/torchaudio ~2,5 GB e pinna transformers/accelerate) (dev: `pytest`, `pytest-asyncio`, `respx`).

Na primeira execução os modelos são baixados automaticamente:
- Whisper (faster-whisper) para o cache do ctranslate2;
- Kokoro (`kokoro-v1.0.onnx` + vozes) para `~/.cache/pipecat/kokoro-onnx/`;
- Qwen3-TTS (~1,5–2 GB) para `~/.cache/huggingface` (só quando `TTS_PROVIDER=qwen3`).

## Hermes

Habilite o API server em `~/.hermes/.env`:

```env
API_SERVER_ENABLED=true
API_SERVER_KEY=uma-chave-local-qualquer
```

O gateway pode ser iniciado manualmente (o API server sobe junto) ou automaticamente pelo `./polaris.sh`:

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
./polaris.sh
```

O `polaris.sh` faz tudo: sobe o `hermes gateway` (se ainda não estiver no ar — reutiliza um já rodando), espera o health check responder, ajusta o `LD_LIBRARY_PATH` para as libs CUDA instaladas via pip (o ctranslate2 do Whisper precisa delas quando `STT_DEVICE=cuda`) e então roda o agente. Ctrl+C encerra tudo — inclusive o gateway que ele subiu. Com `STT_DEVICE=cpu` você pode rodar `uv run python app.py` diretamente (com o Hermes já no ar).

Fale no microfone. O Polaris detecta o fim do turno, transcreve, envia ao Hermes e começa a responder enquanto a resposta ainda está sendo gerada. Ctrl+C para encerrar.

Para usar uma voz da ElevenLabs em vez do Kokoro, configure no `.env`:

```env
TTS_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=...   # chave da API
ELEVENLABS_VOICE_ID=...  # id da voz (premade ou clonada)
```

## Voz Qwen3-TTS (local, GPU)

Roda o **Qwen3-TTS 0.6B** (Apache-2.0) localmente na sua GPU NVIDIA — sem custo por uso, com qualidade superior ao Kokoro, porém **mais lento** (em GPUs de consumo cada sentença leva alguns segundos de síntese; a primeira fala também paga o carregamento do modelo no startup). Para latência mínima, mantenha o ElevenLabs.

```env
TTS_PROVIDER=qwen3
QWEN3_MODEL=Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice   # ou ...-0.6B-Base (clonagem de voz)
QWEN3_DEVICE=cuda            # cuda, cuda:0, cpu ou auto
QWEN3_DTYPE=bfloat16         # float16, bfloat16 ou float32
QWEN3_SPEAKER=Ryan           # voz padrão (todas abaixo)
QWEN3_INSTRUCT=              # estilo opcional, ex.: "Fale devagar e com calma."
```

Vozes do CustomVoice (nenhuma é nativa em português — fala em pt-BR com sotaque):

| Voz | Perfil | Língua nativa |
|---|---|---|
| Vivian | Feminina jovem e clara | Chinês |
| Serena | Feminina suave e gentil | Chinês |
| Uncle_Fu | Masculina madura e aveludada | Chinês |
| Dylan | Masculina jovem (Pequim) | Chinês |
| Eric | Masculina animada (Chengdu) | Chinês |
| Ryan | Masculina dinâmica e ritmada | Inglês |
| Aiden | Masculina americana ensolarada | Inglês |
| Ono_Anna | Feminina japonesa brincalhona | Japonês |
| Sohee | Feminina coreana calorosa | Coreano |

**Clonagem de voz** (modelo `-Base`): clone a voz de um áudio de referência de ~3s — aí sim é possível uma voz nativa em português:

```env
QWEN3_MODEL=Qwen/Qwen3-TTS-12Hz-0.6B-Base
QWEN3_REF_AUDIO=/caminho/para/ref.wav   # arquivo local ou URL (~3s)
QWEN3_REF_TEXT=transcrição do áudio     # vazio = só o timbre, sem transcrição
```

Opções avançadas: `QWEN3_ATTN_IMPLEMENTATION` (vazio = sdpa; ou `flash_attention_2`, requer flash-attn instalado), `QWEN3_MAX_NEW_TOKENS` (default 4096), `QWEN3_TOP_P`.

## Wake word

O Polaris pode ficar "dormindo" até ouvir uma frase de ativação (detectada na transcrição do Whisper — nenhum modelo extra):

```env
WAKE_WORD_ENABLED=true
WAKE_WORD_PHRASES=E aí, Polaris;Ei, Polaris;Polaris, tá aí?   # lista separada por ';'
WAKE_WORD_TIMEOUT=10     # segundos de inatividade até voltar a dormir
```

Comportamento: enquanto dorme, nada vai ao Hermes (as falas são descartadas); ao ouvir uma das frases, o Polaris acorda e a conversa flui normalmente; após `WAKE_WORD_TIMEOUT` segundos sem fala, volta a dormir. O casamento é tolerante: ignora maiúsculas, pontuação e acentos (o Whisper costuma transcrever "polares" em vez de "Polaris" e omitir acentos — ambas as variantes são aceitas automaticamente).

Exemplo de conversa:

> Você: "Que arquivos existem no meu projeto?"
> Polaris (via Hermes + terminal): "Encontrei os seguintes arquivos..."

## Testes

```bash
uv run pytest -q
```

A suíte cobre: configuração, criação do pipeline, parsing SSE, conversão de chunks em frames, `[DONE]`, erros HTTP, sessão, interrupção/cancelamento e fillers de progresso (seleção de frases, watchdog de silêncio, cancelamento no barge-in) — tudo com um Hermes fake (respx), sem rede e sem modelos reais.

## Troubleshooting

| Sintoma | Solução |
|---|---|
| `Hermes API server is offline` | Rode `hermes gateway` e confira `API_SERVER_ENABLED=true` em `~/.hermes/.env` |
| HTTP 401 do Hermes | `HERMES_API_KEY` do `.env` precisa ser igual a `API_SERVER_KEY` de `~/.hermes/.env` |
| Porta 8642 ocupada | Mude `API_SERVER_PORT` em `~/.hermes/.env` e `HERMES_BASE_URL` no `.env` |
| Sem captura de áudio | Liste dispositivos e use `AUDIO_IN_DEVICE`/`AUDIO_OUT_DEVICE` (índices PyAudio) |
| Erro ao instalar (`portaudio.h`) | `sudo apt-get install -y portaudio19-dev` e rode `uv sync` de novo |
| Download do modelo Whisper lento | O primeiro turno baixa o modelo; use `STT_MODEL=base` para máquinas modestas |
| `Library libcublas.so.12 is not found` | Rode via `./polaris.sh` (expõe as libs CUDA do pip via `LD_LIBRARY_PATH`) ou use `STT_DEVICE=cpu` |
| Sem áudio do Kokoro | Confira `~/.cache/pipecat/kokoro-onnx/` (modelo + vozes); teste `TTS_VOICE=pm_alex` |
| Sem áudio do ElevenLabs (log mostra erro de watchdog do TTS) | Vozes **library** (ex.: Fernanda) exigem plano pago: a API devolve `402 paid_plan_required` no free. No free só funcionam vozes **premade** via API — teste com `curl -X POST https://api.elevenlabs.io/v1/text-to-speech/{voice}?model_id=eleven_flash_v2_5 -H "xi-api-key: $ELEVENLABS_API_KEY" -H "Content-Type: application/json" -d '{"text":"oi"}'` |
| Sem áudio do Qwen3 | Confira `nvidia-smi` (GPU visível?) e o log de carregamento "Loading Qwen3-TTS model..."; o download do modelo (~1,5–2 GB) só acontece na primeira execução, para `~/.cache/huggingface` — máquina offline falha no startup |
| Warning `SoX could not be found` no Qwen3 | Inofensivo — o binário do SoX é usado só pelo tokenizer de 25 Hz dos modelos 1.7B; o 0.6B (12 Hz) não precisa |
| `CUDA out of memory` do Qwen3 | Reduza `QWEN3_MAX_NEW_TOKENS` (ex.: 2048) ou use `QWEN3_DTYPE=float16` |
| Primeira fala do Qwen3 demorada | Esperado: o modelo carrega no startup e a síntese em GPU de consumo é mais lenta que tempo real (RTF > 1) — para latência mínima use ElevenLabs |
| Latência alta | `STT_MODEL=base` (ou `tiny`), `STT_COMPUTE_TYPE=int8`, e menos tempo de silêncio no VAD |
| Não acorda com a wake word | Confira `WAKE_WORD_ENABLED=true` e as frases em `WAKE_WORD_PHRASES` (separadas por `;`); pontuação, acentos e as grafias "Polaris"/"Polares" já são normalizados automaticamente — se mesmo assim não acordar, rode com `LOG_LEVEL=DEBUG` e veja as transcrições do Whisper (`STT`/`wake phrase detected`) para conferir como ele está transcrevendo a frase |
| Respostas truncadas/interrompidas | Confira microfone (o VAD pode estar interpretando ruído como barge-in) |

## Roadmap

- Wake word, barge-in avançado, streaming STT
- Transportes WebRTC/WebSocket (web e mobile) — a arquitetura já isola o transport
- Interface web e múltiplos usuários
- Observabilidade avançada (métricas end-to-end)

A spec original do projeto está em `docs/Implementação de agente de voz com Pipecat + Hermes Agent.md`.
