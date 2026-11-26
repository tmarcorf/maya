# Maya

MVP da Maya, uma agente de voz em tempo real para conversar, usando **LiveKit Agents**
(Python). Fluxo: você fala, a Maya detecta o fim da fala e responde por voz.
Interrupção (barge-in) está ligada: se você falar enquanto ela responde, ela para e
escuta.

Stack atual:

- STT local com **faster-whisper** (modelo `medium` por padrão)
- LLM **DeepSeek** (`deepseek-flash`, com thinking desligado)
- TTS **ElevenLabs** (`eleven_flash_v2_5`)
- Pesquisa na web via **Tavily** (chave opcional; keyless como fallback)
- Extração de páginas via **Tavily Extract**
- Data/hora local, cálculo seguro, Wikipedia
- Clima atual e previsão via **Open-Meteo**
- Mercado/índices e cotação de ação via **Yahoo Finance**
- Cache TTL em memória para busca e extração
- VAD Silero + turn detector multimodal multilíngue do LiveKit (`pt` suportado)
- Endpointing configurável por `.env`
- Português do Brasil por padrão, com troca para inglês por configuração
- Memória apenas da conversa atual
- Log de latência por turno: fim da fala -> início do áudio do agente

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
│   └── maya.md
├── src/
│   └── maya_agent/
│       ├── __init__.py
│       ├── __main__.py
│       ├── agent.py
│       ├── config.py
│       ├── instructions.py
│       ├── latency.py
│       ├── session.py
│       ├── stt_whisper.py
│       ├── llm_deepseek.py
│       ├── tts_elevenlabs.py
│       └── tools/
│           ├── __init__.py
│           ├── cache.py
│           ├── calculator.py
│           ├── market.py
│           ├── text.py
│           ├── time_tool.py
│           ├── weather.py
│           ├── web_extract.py
│           ├── web_search.py
│           └── wikipedia.py
└── tests/
    ├── test_agent.py
    ├── test_cache.py
    ├── test_calculator.py
    ├── test_config.py
    ├── test_instructions.py
    ├── test_latency.py
    ├── test_llm_deepseek.py
    ├── test_market.py
    ├── test_session.py
    ├── test_stt_whisper.py
    ├── test_text.py
    ├── test_time_tool.py
    ├── test_tts_elevenlabs.py
    ├── test_weather.py
    ├── test_web_extract.py
    ├── test_web_search.py
    └── test_wikipedia.py
```

## Pré-requisitos

- Python 3.11+ (o `uv` pode instalar/gerenciar)
- [uv](https://docs.astral.sh/uv/)
- Docker (opcional, para o servidor LiveKit local) ou o binário `livekit-server`
- Chave da **DeepSeek** (LLM)
- Chave e voz da **ElevenLabs** (TTS)
- GPU NVIDIA é opcional; o Whisper roda em CUDA com fallback automático para CPU
- A busca na web usa Tavily; a chave é opcional e o modo keyless funciona com limites
- Clima e mercado usam Open-Meteo/Yahoo e não exigem chave

## Setup rápido

1. Entre no projeto e instale as dependências:

   ```bash
   cd maya
   uv sync
   ```

2. Crie o `.env` e preencha as chaves:

   ```bash
   cp .env.example .env
   ```

   Se o `.env` já existir configurado, não copie por cima; apenas confira as chaves.

   Mínimo para o padrão:

   ```dotenv
   DEEPSEEK_API_KEY=...
   ELEVENLABS_API_KEY=...
   ELEVENLABS_VOICE_ID=...
   ```

3. Baixe os arquivos locais de modelo (Silero VAD):

   ```bash
   uv run python -m livekit.agents download-files
   ```

   O faster-whisper baixa o modelo `medium` na primeira execução e reutiliza o cache
   do Hugging Face em `~/.cache/huggingface/hub`. Se o projeto Maya já baixou o
   `faster-whisper-medium`, não há novo download.

4. Teste o loop de voz no terminal (não precisa de servidor LiveKit):

   ```bash
   ./run.sh console
   ```

   O `run.sh` expõe as bibliotecas CUDA instaladas via pip no `LD_LIBRARY_PATH`
   antes de iniciar o Python. Sem o wrapper, o Whisper pode cair para CPU.

5. Fale em pt-BR, espere a resposta e teste interromper o agente enquanto ele fala.
   No terminal aparece uma linha por turno:

   ```text
   turn latency: end of speech -> first agent audio: 842 ms
   ```

6. Suba o servidor LiveKit local (alternativa: `livekit-server --dev`):

   ```bash
   docker compose up -d
   ```

   O modo dev usa `LIVEKIT_URL=ws://127.0.0.1:7880`, `LIVEKIT_API_KEY=devkey` e
   `LIVEKIT_API_SECRET=secret` (já são os valores do `.env.example`).

7. Rode o agente conectado ao servidor local:

   ```bash
   ./run.sh dev
   ```

8. Abra o [Agents Playground](https://agents-playground.livekit.io), conecte em
   `ws://127.0.0.1:7880` com `devkey` / `secret`, entre em uma sala e fale. Como a
   Maya não define `agent_name`, ela é despachada automaticamente para novas salas.

   Se a versão hospedada do Playground não aceitar um servidor local, rode o
   [playground localmente](https://github.com/livekit/agent-playground) apontando
   `NEXT_PUBLIC_LIVEKIT_URL=ws://127.0.0.1:7880` e as mesmas credenciais.

> A CLI embutida do Python (`console`/`dev`) está depreciada no `livekit-agents`
> 1.9.0, mas continua funcionando nesta versão (aparece um aviso). O caminho novo é
> instalar a [LiveKit CLI](https://docs.livekit.io/reference/developer-tools/livekit-cli/)
> e usar `lk agent console` / `lk agent dev`. Para o download de modelos, o comando
> atual é `uv run python -m livekit.agents download-files`.

## Comandos úteis

```bash
./run.sh console                 # console com CUDA configurado
./run.sh dev                     # modo dev conectado ao LiveKit
uv run python -m maya_agent console
uv run pytest                    # testes
uvx ruff check .                 # lint
```

## Whisper local

O adaptador `stt_whisper.py` usa `faster-whisper` no próprio processo do job.
Configuração padrão:

```dotenv
WHISPER_MODEL=medium
WHISPER_DEVICE=auto       # ou cuda / cpu
WHISPER_COMPUTE_TYPE=default  # ou float16 (GPU) / int8 (CPU)
```

Se a carga em CUDA falhar, o adaptador registra um aviso e tenta `cpu` com `int8`.
O modelo é pré-carregado em uma thread no início da sessão.

## DeepSeek

```dotenv
DEEPSEEK_API_KEY=...
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_TEMPERATURE=0.6
```

O código desliga o *thinking* mode para baixa latência. `deepseek-v4.1-flash-1017`
é o nome da versão por trás do modelo; o nome aceito pela API é `deepseek-flash`.
O adapter usa o plugin oficial `openai.LLM` apenas como transporte
OpenAI-compatible.

## ElevenLabs

```dotenv
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=...
ELEVENLABS_MODEL_ID=eleven_flash_v2_5
```

O idioma é passado como `pt` (ou `en`) a partir de `MAYA_LANGUAGE`.

## Pesquisa na web (Tavily)

A tool `web_search` usa a API do Tavily. A chave é opcional; sem ela o cliente
usa o modo keyless.

```dotenv
TAVILY_API_KEY=          # opcional
WEB_SEARCH_ENABLED=true
WEB_SEARCH_MAX_RESULTS=3
WEB_SEARCH_TIMEOUT_SECONDS=8
WEB_SEARCH_CACHE_TTL_MINUTES=10
```

- Com `TAVILY_API_KEY`, usa `Authorization: Bearer` e maior limite.
- Sem chave, usa `X-Tavily-Access-Mode: keyless` (sujeito a rate limit).
- `search_depth=fast` e `include_answer=basic`: a resposta traz um resumo curto
  mais snippets das fontes.
- `WEB_SEARCH_ENABLED=false` remove a tool do agente.
- O cache TTL evita repetir a mesma busca; `0` desliga o cache.
- O DeepSeek decide quando chamar a tool e resume em 1–3 frases.
- Resultados da web são tratados como dados não confiáveis; o prompt proíbe
  seguir instruções contidas neles e proíbe ler URLs em voz alta.
- Se o Tavily falhar ou limitar, a Maya avisa que não conseguiu verificar agora;
  não é um erro fatal do turno.
- Tavily é busca web, não fonte de dados ao vivo. Para clima e cotações, use
  `get_weather` e `get_market_summary`.

Quando houver um segundo backend (SearXNG ou Brave), ele entra como outro
`WebSearchClient` em `tools/web_search.py`; a tool e os testes continuam iguais.

## Extração de páginas (web_extract)

Depois de uma busca, o LLM pode pedir o conteúdo real de uma ou duas páginas.

```dotenv
WEB_EXTRACT_ENABLED=true
WEB_EXTRACT_MAX_URLS=2
WEB_EXTRACT_MAX_CHARS=6000
WEB_EXTRACT_TIMEOUT_SECONDS=8
WEB_EXTRACT_CACHE_TTL_MINUTES=10
```

- Usa o mesmo `TAVILY_API_KEY` da busca.
- O conteúdo é limpo, truncado e cacheado por URL.
- O prompt proíbe ler URLs em voz alta; a Maya usa o conteúdo para responder.

## Clima (get_weather / get_weather_forecast)

As tools de clima usam o Open-Meteo, sem chave.

- `get_weather(city)`: temperatura, sensação, condição, vento, umidade e horário.
- `get_weather_forecast(city, days)`: previsão de 1 a 7 dias, com máxima, mínima,
  chance de chuva e vento.
- Erros viram uma mensagem curta; a Maya não inventa dados.

## Mercado (get_market_summary / get_stock_quote)

As tools de mercado usam o Yahoo Finance, sem chave.

- `get_market_summary()`: Ibovespa, S&P 500, Nasdaq e Dow Jones.
- `get_stock_quote(symbol)`: uma ação específica; `PETR4` vira `PETR4.SA`
  automaticamente.
- Inclui preço, variação, variação percentual, moeda e horário.
- É o caminho correto para “como estão as ações hoje”; não use web_search
  para cotações ao vivo.

## Data, cálculo e Wikipedia

```dotenv
MAYA_TIMEZONE=America/Sao_Paulo
```

- `get_current_datetime`: data, hora, dia da semana, fuso e offset.
- `calculate`: aritmética segura com `ast`, sem `eval`; suporta parênteses,
  `+ - * / // % **` e limites de tamanho/expoente.
- `wikipedia`: resumo em português ou inglês, conforme `MAYA_LANGUAGE`, sem chave.

## Idioma e prompt

```dotenv
MAYA_LANGUAGE=pt-BR   # padrão
# MAYA_LANGUAGE=en-US
MAYA_PROMPT_PATH=prompts/maya.md
MAYA_TIMEZONE=America/Sao_Paulo
```

A persona fica em `prompts/maya.md` e pode ser editada diretamente. O caminho
é configurável para facilitar deploy/montagem do arquivo. `MAYA_TIMEZONE` também
define o fuso usado por `get_current_datetime`.

## Turn detection, endpointing e barge-in

- `TURN_DETECTOR_VERSION=v1-mini` roda o modelo multimodal localmente na CPU, sem
  depender do LiveKit Cloud. Use `v1` para a versão completa via LiveKit Inference
  (exige credenciais do LiveKit Cloud; sem elas o SDK cai para `v1-mini`).
- `ENDPOINTING_MODE=fixed` ou `dynamic`
- `MIN_ENDPOINTING_DELAY=0.3` e `MAX_ENDPOINTING_DELAY=2.5` (segundos; padrões do
  detector multimodal)
- `MIN_INTERRUPTION_DURATION=0.4` filtra ruídos curtos antes de interromper o agente

As respostas são mantidas em 1 a 3 frases pelo prompt. O LiveKit também aplica, por
padrão, filtros de markdown e emoji no texto enviado ao TTS.

## Extensão futura: adicionar um provider

Quando existir um segundo backend para a mesma capacidade, aí sim criar o seam
de seleção:

1. Criar o módulo do adapter (ex.: `tools/searxng.py` ou `tts_<provider>.py`)
   com a mesma interface de builder/client.
2. Adicionar a config específica em `config.py` e ler o seletor no `.env`.
3. Introduzir uma factory/union no ponto de composição.
4. Atualizar `.env.example`, README e testes.

Para `web_search`, o primeiro adapter é `TavilySearchClient`. O próximo
(SearXNG ou Brave) implementa `WebSearchClient` e só precisa trocar o client no
`build_web_search_tool`.

Até lá, não há factory/registry: um adapter por tipo mantém o código direto.

## Solução de problemas

- **Erro de PortAudio no console**: instale `libportaudio2` (Linux) e confira o
  microfone/alto-falante. A CLI legada permite escolher os dispositivos ao iniciar.
- **`libcublas.so.12` ou `libcudnn.so.9` não encontrados**: use `./run.sh` (ele
  ajusta o `LD_LIBRARY_PATH`). Se não houver GPU disponível, use
  `WHISPER_DEVICE=cpu` e `WHISPER_COMPUTE_TYPE=int8`.
- **Primeira transcrição lenta**: o modelo Whisper é carregado/baixado na primeira
  sessão; depois fica em cache no processo e no disco.
- **ElevenLabs 401/403**: confira `ELEVENLABS_API_KEY` e `ELEVENLABS_VOICE_ID`.
- **`DEEPSEEK_API_KEY is required`**: a chave da DeepSeek não foi preenchida no `.env`.
- **Busca na web falhando/timeout**: confira `TAVILY_API_KEY` e o limite da conta.
  Sem chave, o modo keyless pode ser rate-limitado. A Maya avisa que não conseguiu
  verificar; tente de novo ou aumente `WEB_SEARCH_TIMEOUT_SECONDS`. Para desligar,
  use `WEB_SEARCH_ENABLED=false`.
- **`web_extract` falhando**: confira a URL e o limite do Tavily; páginas com
  JavaScript pesado podem retornar pouco conteúdo. Ajuste `WEB_EXTRACT_MAX_CHARS`
  ou use a busca como fallback.
- **Clima/mercado indisponíveis**: Open-Meteo e Yahoo podem falhar ou limitar.
  A Maya avisa; tente novamente depois. Nenhuma chave é necessária.
- **`MAYA_TIMEZONE` inválido**: use um nome IANA, como `America/Sao_Paulo` ou
  `Europe/Berlin`.
- **Cálculo rejeitado**: `calculate` aceita só aritmética básica; não aceita
  funções, variáveis ou expressões muito grandes.
- **Wikipedia sem resultado**: confira o termo ou tente `web_search`; a tool usa
  o idioma configurado em `MAYA_LANGUAGE`.
- **Falha ao conectar no LiveKit**: confirme `docker compose ps`, a URL e as
  credenciais. O modo dev do LiveKit usa `devkey` / `secret`.
- **Aviso de chave HMAC curta**: esperado com `devkey` / `secret` do modo dev local;
  não afeta o funcionamento.

## Limitações deste MVP

Sem RAG, memória persistente, wake word, UI customizada, telefonia/SIP, vídeo,
autenticação ou deploy de produção.
