# Maya

Maya é a camada de voz em tempo real. O cérebro — LLM, ferramentas, memória,
skills e cron — fica no [Hermes Agent](https://github.com/NousResearch/hermes-agent).
A Maya cuida de VAD, STT, turn-taking, barge-in e TTS; o Hermes recebe texto e
devolve texto em stream.

```text
Voz -> Maya (VAD / faster-whisper / turn-taking)
         -> HermesLLM -> Hermes API Server /p/maya-voice/v1
                          -> DeepSeek + tools + memória + skills
         <- stream de texto -> ElevenLabs TTS -> Voz
```

Stack da camada de voz:

- STT local com **faster-whisper** (modelo `medium` por padrão)
- TTS **ElevenLabs** (`eleven_flash_v2_5`)
- VAD Silero + turn detector multimodal multilíngue do LiveKit
- **Hermes API Server** como LLM e executor de ferramentas
- Modelo **DeepSeek** configurado no perfil do Hermes
- Português do Brasil por padrão, com troca para inglês por configuração
- Log de latência estruturado por turno
- Página local de aprovação para comandos perigosos

## Estrutura

```text
maya/
├── pyproject.toml
├── .env.example
├── README.md
├── AGENTS.md
├── docker-compose.yml
├── run.sh
├── prompts/
│   └── maya.md              # contrato de formato de voz (efêmero)
├── src/
│   └── maya_agent/
│       ├── __init__.py
│       ├── __main__.py
│       ├── agent.py
│       ├── approvals.py     # página/CLI local de aprovação
│       ├── config.py
│       ├── instructions.py
│       ├── latency.py
│       ├── llm_hermes.py    # adaptador SSE do API server
│       ├── session.py
│       ├── stt_whisper.py
│       ├── tts_elevenlabs.py
│       └── tools/           # legado: mantido, mas não ligado ao Agent
└── tests/
```

## Pré-requisitos

- Python 3.11+ e [uv](https://docs.astral.sh/uv/)
- Hermes Agent instalado (`hermes --version`)
- Chave e voz da **ElevenLabs**
- Chave da **DeepSeek** no perfil do Hermes
- GPU NVIDIA é opcional; o Whisper roda em CUDA com fallback automático para CPU
- Docker (opcional, para um LiveKit server local) ou o binário `livekit-server`

## Hermes: perfil `maya-voice`

A Maya usa um perfil Hermes separado. O perfil `default` do Hermes já se chama
"Maya"; para não criar duas Mayas, o perfil da voz se chama `maya-voice`.

```bash
hermes profile create maya-voice --clone-from default --no-alias
hermes -p maya-voice config set stt.enabled false
hermes -p maya-voice config set voice.auto_tts false
hermes -p maya-voice config set platform_toolsets.api_server \
  '["web","browser","terminal","file","code_execution","vision","video","image_gen","video_gen","x_search","skills","todo","kanban","memory","context_engine","session_search","connections","clarify","delegation","cronjob","discord","discord_admin","computer_use","a2a","homeassistant","spotify"]'
hermes -p maya-voice config set platforms.api_server.tool_progress_events true
hermes -p maya-voice config set platforms.api_server.approval_events true
hermes -p maya-voice skills install official/finance/stocks --yes
```

Edite `~/.hermes/profiles/maya-voice/.env` e defina:

```dotenv
API_SERVER_ENABLED=true
API_SERVER_KEY=uma-chave-forte
DEEPSEEK_API_KEY=...
```

O perfil `maya-voice` usa o modelo `deepseek-flash` e o backend de terminal
local. O `SOUL.md` do perfil define a persona; `prompts/maya.md` define apenas o
formato falado.

Reinicie o gateway e confira:

```bash
hermes gateway restart
curl -H "Authorization: Bearer $API_SERVER_KEY" \
  http://127.0.0.1:8642/p/maya-voice/v1/models
```

O plugin de clima (`hermes -p maya-voice plugins install weather`) é opcional e
pesado: alguns caminhos exigem Rust. Sem ele, clima é resolvido por busca na web.

## Configuração da Maya

```bash
cp .env.example .env
```

Mínimo:

```dotenv
HERMES_BASE_URL=http://127.0.0.1:8642/p/maya-voice/v1
HERMES_API_KEY=uma-chave-forte
HERMES_MODEL=hermes-agent
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=...
```

A Maya **não** precisa de `DEEPSEEK_API_KEY`; ela só fala com o Hermes.

## Rodar

```bash
uv sync
uv run python -m livekit.agents download-files
./run.sh console
```

O `run.sh` expõe as bibliotecas CUDA instaladas via pip no `LD_LIBRARY_PATH`.
Sem ele, o Whisper pode cair para CPU.

No console, cada turno gera uma linha como:

```text
turn latency: end of speech -> first agent audio: 842 ms {"room": "...", "session_id": "...", "first_audio_ms": 842, "first_token_ms": 312, "tool_ack_ms": null}
```

## Como a integração funciona

- A Maya manda apenas a **última fala** do usuário para o Hermes.
- `X-Hermes-Session-Id` é fixo por sala LiveKit: cada chamada começa um
  transcript novo no Hermes.
- `X-Hermes-Session-Key` escopa a memória de longo prazo do usuário.
- O Hermes é dono do transcript, das ferramentas e da memória; a Maya não
  registra ferramentas locais.
- Eventos `hermes.tool.progress` viram falas curtas de progresso via
  `session.say(..., add_to_chat_ctx=False)`.
- Eventos `approval.request` abrem a página local de aprovação
  (`http://127.0.0.1:8765/`) e disparam `notify-send`. O Hermes Desktop continua
  sendo a superfície principal quando enxerga o run.
- Se o Hermes estiver fora do ar, a Maya fala um erro curto e tenta uma vez.

## Ferramentas

As ferramentas antigas da Maya continuam no repositório, mas não estão ligadas ao
`Agent`. Quem executa ferramentas é o Hermes:

- terminal, arquivos, código, browser, web, visão, memória, skills, cron,
  subagentes, `computer_use`
- mercado/ações via skill oficial `finance/stocks` (Yahoo Finance)
- clima via busca na web (ou plugin `weather`, se habilitado)

## Comandos úteis

```bash
./run.sh console                 # console com CUDA configurado
./run.sh dev                     # modo dev conectado ao LiveKit
uv run pytest                    # testes
uvx ruff check .                 # lint
```

## Testes

Os testes não carregam `.env`, não baixam modelos e não fazem chamadas de rede.
O adaptador do Hermes é testado com um transporte SSE falso.

## Troubleshooting

- `401` no Hermes: `HERMES_API_KEY` da Maya difere do `API_SERVER_KEY` do perfil.
- `404` no Hermes: confira `HERMES_BASE_URL` e o prefixo `/p/maya-voice/v1`.
- Aprovação não aparece: abra `http://127.0.0.1:8765/`; confira `notify-send`.
- Hermes lento: meça `first_token_ms` e `tool_ack_ms`; o perfil usa
  `deepseek-flash` com reasoning desligado.
