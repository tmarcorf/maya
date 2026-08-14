# Implementação de um agente de voz com Pipecat + Hermes Agent

Quero construir um agente de IA controlado por voz utilizando **Python**, **Pipecat** como camada de voz/orquestração em tempo real e **Hermes Agent** como cérebro/executor.

A arquitetura desejada é:

```text
                         Usuário
                           🎙️
                            │
                            ▼
                 ┌──────────────────────┐
                 │      PIPECAT         │
                 │                      │
                 │  Audio Input         │
                 │       ↓              │
                 │      STT             │
                 │       ↓              │
                 │  VAD / Turn Detect   │
                 │       ↓              │
                 │  Context             │
                 │       ↓              │
                 │  Hermes Adapter      │
                 │       ↓              │
                 │      TTS             │
                 │       ↓              │
                 │  Audio Output        │
                 └──────────┬───────────┘
                            │
                            │ streaming
                            ▼
                 ┌──────────────────────┐
                 │    HERMES AGENT      │
                 │                      │
                 │ LLM                  │
                 │ Tools                │
                 │ Terminal             │
                 │ Browser              │
                 │ Memory               │
                 │ Skills               │
                 │ Subagents            │
                 └──────────────────────┘
```

## Objetivo

Construir uma primeira versão funcional de um assistente de voz local em que:

```text
voz
 ↓
Pipecat
 ↓
STT
 ↓
Hermes Agent
 ↓
streaming
 ↓
Pipecat
 ↓
TTS
 ↓
voz
```

O **Hermes é o cérebro e executor**.

O Pipecat não deve duplicar as responsabilidades do Hermes.

O Pipecat deve cuidar de:

- captura de áudio;
- transporte;
- VAD;
- turn detection;
- STT;
- pipeline assíncrono;
- streaming;
- TTS;
- reprodução de áudio;
- interrupções;
- gerenciamento de frames;
- métricas.

O Hermes deve cuidar de:

- raciocínio;
- LLM;
- execução de ferramentas;
- terminal;
- arquivos;
- browser;
- memória;
- skills;
- subagentes;
- execução das tarefas solicitadas pelo usuário.

---

# 1. Antes de implementar

Primeiro consulte a documentação e o código atuais de:

- Pipecat;
- Hermes Agent.

Não assuma que exemplos antigos continuam válidos.

Valide especificamente:

### Hermes

- API Server;
- `/v1/chat/completions`;
- `/v1/responses`;
- streaming SSE;
- `X-Hermes-Session-Id`;
- eventos de tool progress;
- autenticação;
- formato real dos chunks;
- comportamento de sessões;
- interrupção/cancelamento.

### Pipecat

- API atual;
- `Pipeline`;
- `PipelineTask`;
- `LLMService`;
- integração OpenAI-compatible;
- STT;
- TTS;
- VAD;
- turn detection;
- interrupção;
- transports.

Não implemente um adapter baseado apenas em suposições.

Se o Pipecat já possuir uma abstração adequada para consumir um endpoint OpenAI-compatible, utilize-a.

Se o comportamento específico do Hermes exigir um adapter/frame processor customizado, implemente somente a camada necessária.

---

# 2. Princípio arquitetural

A aplicação deve ter uma separação clara:

```text
┌──────────────────────────────────────┐
│              Pipecat                 │
│                                      │
│ Audio → STT → Context → Hermes → TTS│
│                                      │
└──────────────────┬───────────────────┘
                   │
                   │ HTTP/SSE
                   ▼
┌──────────────────────────────────────┐
│           Hermes Agent               │
│                                      │
│ Agent runtime completo               │
└──────────────────────────────────────┘
```

Não implemente manualmente um segundo agent runtime.

Não coloque lógica de ferramentas dentro do Pipecat.

Não replique a memória do Hermes no Pipecat sem necessidade.

O Pipecat deve tratar Hermes como um serviço externo de inteligência/agente.

---

# 3. Streaming é requisito fundamental

Quero uma arquitetura verdadeiramente orientada a streaming.

Não quero:

```text
gravar áudio inteiro
↓
esperar
↓
STT inteiro
↓
esperar
↓
Hermes inteiro
↓
esperar
↓
TTS inteiro
↓
reproduzir
```

Quero:

```text
áudio
  ↓
STT
  ↓
final do turno
  ↓
Hermes
  ↓
tokens/chunks
  ↓
TTS
  ↓
áudio
```

Enquanto o Hermes estiver produzindo uma resposta, o Pipecat deve começar a processar o texto para TTS assim que houver conteúdo suficiente.

Não espere a resposta completa do Hermes para iniciar o TTS.

Utilize as abstrações nativas de streaming do Pipecat.

O Pipecat já trabalha com `LLMTextFrame`s e pode encaminhá-los ao TTS enquanto a resposta está sendo gerada.

---

# 4. STT

Utilize o sistema de STT do próprio Pipecat.

Para a primeira versão, prefiro uma solução local:

```text
Pipecat
   ↓
WhisperSTTService
   ↓
Faster Whisper
```

A configuração deve permitir:

```text
STT_MODEL
STT_DEVICE
STT_COMPUTE_TYPE
STT_LANGUAGE
```

Como o usuário é brasileiro, configure inicialmente português brasileiro, mas mantenha a possibilidade de auto-detecção.

Exemplo conceitual:

```env
STT_MODEL=small
STT_DEVICE=cpu
STT_COMPUTE_TYPE=int8
STT_LANGUAGE=pt
```

Não escreva um wrapper manual em torno do faster-whisper se o Pipecat já fornece o serviço necessário.

Utilize a abstração do Pipecat.

Também utilize o VAD/turn detection do Pipecat.

Não implemente manualmente uma lógica de "gravar até ficar 1 segundo em silêncio" se o Pipecat já oferece mecanismos melhores.

---

# 5. TTS

Utilize o sistema de TTS do Pipecat.

Para a primeira versão, prefira uma implementação local.

Avalie:

```text
Kokoro
```

como primeira opção.

O TTS deve funcionar de maneira incremental.

A resposta:

```text
"Vou verificar o projeto e analisar os arquivos."
```

não deve necessariamente esperar toda a resposta para começar.

O Pipecat deve receber os chunks do LLM e agregá-los apropriadamente para o TTS.

Configure inicialmente uma agregação por sentença, evitando mandar tokens individuais demais para o sintetizador.

O TTS deve ser facilmente substituível no futuro.

---

# 6. Hermes Agent

O Hermes deve ser executado separadamente do processo do Pipecat.

Por exemplo:

```text
Processo 1:
Hermes Agent

Processo 2:
Python + Pipecat
```

O Hermes deve expor sua API local.

Exemplo conceitual:

```text
http://127.0.0.1:8642/v1
```

O Pipecat deverá consumir:

```text
POST /v1/chat/completions
```

utilizando streaming.

O Hermes deve continuar sendo responsável por todo o processamento agentivo.

---

# 7. Integração Pipecat → Hermes

Primeiro verifique se o serviço OpenAI-compatible do Pipecat pode consumir diretamente:

```text
http://127.0.0.1:8642/v1
```

com:

```text
model=hermes-agent
```

Se funcionar corretamente, prefira essa abordagem.

Não crie um adapter customizado desnecessariamente.

Entretanto, valide o comportamento real do Hermes durante:

```text
LLM response
tool call
tool execution
tool result
LLM continuation
final response
```

O Hermes pode emitir eventos específicos relacionados à execução de ferramentas.

Se o serviço OpenAI do Pipecat não interpretar corretamente esses eventos, crie um `HermesLLMService` ou `FrameProcessor` específico.

Esse componente deve:

1. enviar a mensagem ao Hermes;
2. manter a sessão correta;
3. consumir SSE;
4. transformar os chunks de texto em `LLMTextFrame`;
5. lidar corretamente com início/fim da resposta;
6. lidar com erros;
7. lidar com cancelamento/interrupção;
8. ignorar ou tratar apropriadamente eventos de tool progress.

---

# 8. Sessão/conversa

A conversa deve permanecer coerente entre os turnos.

Antes de implementar uma memória local, verifique o mecanismo de sessão do Hermes.

Se o Hermes fornecer:

```text
X-Hermes-Session-Id
```

ou mecanismo equivalente, utilize-o.

A aplicação Pipecat deve possuir um identificador de sessão, por exemplo:

```text
voice-session-<uuid>
```

e associá-lo à sessão do Hermes.

Não mantenha duas fontes de verdade para histórico sem necessidade.

O Hermes deve continuar sendo a autoridade sobre o estado agentivo.

---

# 9. Interrupção / barge-in

A arquitetura deve ser preparada desde o começo para interrupção.

Exemplo:

```text
Hermes está respondendo
        ↓
TTS está falando
        ↓
Usuário começa a falar
        ↓
Pipecat detecta interrupção
        ↓
TTS para
        ↓
pipeline processa nova fala
        ↓
Hermes recebe nova mensagem
```

Não é necessário implementar uma versão extremamente sofisticada na primeira etapa, mas não construa a arquitetura de maneira que isso seja impossível posteriormente.

Utilize os mecanismos nativos de interrupção do Pipecat.

---

# 10. Transport

Para a primeira versão, escolha o transport mais simples que permita testar:

```text
microfone local
        ↓
Pipecat
        ↓
speaker local
```

Se existir um transport local apropriado no Pipecat, utilize-o.

Não crie frontend web inicialmente.

Entretanto, deixe a arquitetura preparada para posteriormente suportar:

```text
Browser
WebRTC
WebSocket
Mobile
```

através dos transports do Pipecat.

---

# 11. Estrutura do projeto

Crie uma estrutura simples e alinhada ao modelo do Pipecat.

Sugestão:

```text
voice-hermes/
│
├── app.py
├── pyproject.toml
├── README.md
├── .env.example
├── .gitignore
│
├── config/
│   └── settings.py
│
├── pipeline/
│   ├── __init__.py
│   ├── voice_pipeline.py
│   └── hermes.py
│
└── utils/
    ├── __init__.py
    └── logging.py
```

Não crie classes abstratas para tudo.

Use as abstrações fornecidas pelo Pipecat.

---

# 12. Configuração

Utilize `.env`.

Exemplo:

```env
# Hermes
HERMES_BASE_URL=http://127.0.0.1:8642/v1
HERMES_API_KEY=change-me-local-dev
HERMES_MODEL=hermes-agent
HERMES_SESSION_ID=

# STT
STT_MODEL=small
STT_DEVICE=cpu
STT_COMPUTE_TYPE=int8
STT_LANGUAGE=pt

# TTS
TTS_PROVIDER=kokoro
TTS_LANGUAGE=pt
TTS_VOICE=

# Application
LOG_LEVEL=INFO
```

Não coloque credenciais diretamente no código.

---

# 13. Pipeline desejado

O pipeline deve se aproximar conceitualmente de:

```python
Pipeline([
    transport.input(),
    stt,
    context_aggregator.user(),
    hermes,
    tts,
    transport.output(),
    context_aggregator.assistant(),
])
```

Adapte os componentes conforme a API atual do Pipecat.

O ponto importante é preservar a sequência:

```text
Audio Input
    ↓
STT
    ↓
User Context
    ↓
Hermes
    ↓
Streaming LLM Frames
    ↓
TTS
    ↓
Audio Output
```

---

# 14. Hermes como cérebro, não como simples LLM

Isso é muito importante.

O Hermes não deve ser tratado apenas como:

```text
texto → LLM → texto
```

Ele é um agente com:

```text
LLM
+
Tools
+
Terminal
+
Browser
+
Memory
+
Skills
+
Agent execution
```

Por exemplo, quando o usuário falar:

> "Abra meu projeto ZenMoney e veja por que o backend não está compilando."

O Pipecat deve apenas:

```text
voz
↓
"Abra meu projeto..."
↓
Hermes
```

O Hermes deve então executar as ferramentas necessárias.

O Pipecat não deve tentar decidir como essa tarefa será executada.

---

# 15. Eventos de ferramentas

Não fale automaticamente eventos internos do Hermes.

Por exemplo, se Hermes enviar algo equivalente a:

```text
tool_call
terminal
running command
tool_result
```

não envie isso diretamente para o TTS.

Esses eventos devem ser tratados como eventos de sistema/observabilidade.

No futuro poderemos adicionar mensagens faladas como:

> "Vou verificar isso."

mas isso deve ser uma decisão explícita da camada de voz, não uma leitura literal dos eventos internos.

---

# 16. Observabilidade

Adicione logs para:

```text
STT started
STT final transcript
Hermes request started
Hermes response started
Hermes tool activity
Hermes response completed
TTS started
TTS completed
interruption
errors
```

Também registre métricas importantes:

```text
STT latency
Hermes time-to-first-token
TTS time-to-first-audio
end-to-end latency
```

O objetivo futuro é conseguir medir:

```text
usuário terminou de falar
        ↓
primeiro áudio da resposta
```

Esse será nosso principal indicador de responsividade.

---

# 17. Segurança

Inicialmente Hermes estará disponível somente em:

```text
127.0.0.1
```

Não exponha a API publicamente.

Utilize a API key do Hermes.

Não coloque secrets no Git.

Crie:

```text
.env.example
```

e adicione:

```text
.env
```

ao `.gitignore`.

---

# 18. Dependências

Utilize Python 3.11+.

Prefira `uv` para gerenciamento de dependências se isso estiver alinhado à versão atual do Pipecat.

As dependências principais devem ser fornecidas pelo próprio Pipecat quando possível.

Avalie algo conceitualmente semelhante a:

```text
pipecat-ai
pipecat-ai[whisper]
pipecat-ai[kokoro]
python-dotenv
```

Não adicione `httpx`, `aiohttp`, `faster-whisper`, `sounddevice` etc. manualmente se o Pipecat já encapsular a necessidade correspondente.

Antes de adicionar qualquer dependência, verifique a documentação atual.

---

# 19. Testes

Crie pelo menos testes para:

1. configuração;
2. criação do pipeline;
3. parsing da resposta streaming do Hermes;
4. conversão dos chunks Hermes → Pipecat frames;
5. tratamento de `[DONE]`;
6. tratamento de erro HTTP;
7. sessão Hermes;
8. interrupção/cancelamento.

Não é necessário testar modelos de IA reais nos testes unitários.

Utilize mocks/fakes para Hermes.

---

# 20. README

O README deve explicar:

## Arquitetura

```text
User
 ↓
Pipecat
 ↓
STT
 ↓
Hermes Agent
 ↓
TTS
 ↓
User
```

## Pré-requisitos

- Python 3.11+
- uv
- Pipecat
- Hermes Agent
- microfone
- saída de áudio

## Instalação

Explique os comandos exatos.

## Hermes

Explique como habilitar o API Server e iniciar:

```text
hermes gateway
```

Confirme na documentação atual os comandos corretos antes de escrever.

## Execução

```bash
uv run python app.py
```

## Troubleshooting

Inclua:

- Hermes offline;
- API key incorreta;
- porta ocupada;
- microfone;
- dispositivo de áudio;
- modelo Whisper;
- CUDA;
- modelos Kokoro;
- problemas de latência.

---

# 21. Critério de sucesso

Ao executar:

```bash
uv run python app.py
```

deve ser possível:

1. falar no microfone;
2. Pipecat detectar o turno;
3. converter fala para texto;
4. enviar o texto ao Hermes;
5. Hermes executar ferramentas quando necessário;
6. receber a resposta em streaming;
7. Pipecat transformar a resposta em áudio;
8. ouvir a resposta sem esperar o Hermes terminar completamente;
9. continuar a conversa no próximo turno.

Exemplo:

```text
Usuário:
"Que arquivos existem no meu projeto?"

        ↓

Pipecat
        ↓
STT
        ↓
Hermes
        ↓
Terminal
        ↓
Hermes
        ↓
streaming
        ↓
Pipecat
        ↓
Kokoro
        ↓
Áudio

Hermes fala:
"Encontrei os seguintes arquivos..."
```

---

# 22. O que NÃO implementar ainda

Não implemente nesta primeira versão:

- wake word;
- avatar;
- frontend web;
- mobile;
- banco de dados próprio;
- sistema multiusuário;
- autenticação externa;
- cloud deployment;
- RAG;
- múltiplos Hermes;
- multi-agent orchestration;
- emoções;
- voice cloning;
- processamento de áudio avançado;
- telephony;
- Redis;
- Kafka;
- Kubernetes.

A arquitetura deve permitir esses recursos no futuro, mas o MVP deve permanecer simples.

---

# 23. Evolução futura

A arquitetura deve permitir evoluir para:

```text
                    ┌───────────────┐
                    │    Browser    │
                    │    WebRTC     │
                    └───────┬───────┘
                            │
                            ▼
                    ┌───────────────┐
                    │    Pipecat    │
                    └───────┬───────┘
                            │
                    ┌───────┴───────┐
                    │               │
                    ▼               ▼
                  STT              TTS
                    │               ▲
                    └───────┬───────┘
                            │
                            ▼
                     Hermes Agent
                            │
               ┌────────────┼────────────┐
               ▼            ▼            ▼
            Terminal      Browser      Memory
```

Posteriormente poderemos adicionar:

- wake word;
- barge-in avançado;
- streaming STT;
- WebRTC;
- interface web;
- múltiplos usuários;
- observabilidade;
- execução remota;
- subagentes;
- ferramentas próprias.

---

# 24. Regra principal de implementação

**Não reinvente o Pipecat.**

Se o Pipecat já possui uma solução para:

- VAD;
- STT;
- TTS;
- streaming;
- context;
- interruption;
- transport;
- pipeline;

utilize-a.

**Não reinvente o Hermes.**

Se o Hermes já possui:

- memória;
- sessão;
- ferramentas;
- execução;
- browser;
- terminal;
- skills;

utilize-as.

A aplicação que estamos construindo deve ser essencialmente a ponte:

```text
                    PIPECAT
                       │
                       │
      Voz ─────────────┼───────────── Voz
                       │
                       │
                    HERMES
```

com o mínimo possível de lógica duplicada.

## Entregáveis finais

Ao terminar:

1. Crie todos os arquivos necessários.
2. Mostre a árvore do projeto.
3. Explique a arquitetura.
4. Explique como Pipecat conversa com Hermes.
5. Explique como o streaming funciona.
6. Explique como sessões são mantidas.
7. Explique como interrupções funcionam ou ficarão preparadas.
8. Liste os comandos de instalação.
9. Liste os comandos para executar Hermes.
10. Liste os comandos para executar o voice agent.
11. Execute testes básicos.
12. Faça uma revisão final procurando:
   - imports inválidos;
   - APIs depreciadas;
   - incompatibilidades entre versões;
   - problemas de async;
   - problemas de streaming;
   - problemas de sessão;
   - dependências desnecessárias.

**Antes de escrever o código, valide a documentação atual do Pipecat e do Hermes Agent. Não invente APIs.**