# Maya Desktop

Companion desktop (Electron) do agente de voz Maya — orb 3D reativo aos
estados de voz, chat espelhando a conversa e toggle da wake word sincronizado
com o backend. O app **só conecta**: o backend é subido separadamente com
`./maya.sh` (raiz do repo), que expõe a bridge WebSocket em
`ws://127.0.0.1:8686` (`BRIDGE_WS_PORT`).

## Desenvolvimento (web puro — sem Electron)

```bash
# terminal 1 — mock da bridge (cena scriptada, sem backend real)
npm run mock

# terminal 2 — renderer no navegador
npm run dev:web    # http://localhost:5174
```

O mock implementa o mesmo protocolo de `pipeline/bridge.py` e alterna os
estados (idle → ouvindo → você fala → pensando → falando) com níveis de
áudio sintéticos — dá para ver o orb reagir sem microfone.

Com o backend real (`./maya.sh` na raiz), basta `npm run dev:web`.

## Electron

```bash
npm run dev         # vite + electron (janela de dev, com backend/mock no ar)
node scripts/verify-electron.mjs   # E2E headless: conecta, espelha, toggle
```

No Electron a conexão vive no **processo main** (tray e atalho global
`Ctrl+Shift+Space` funcionam com a janela fechada); o renderer consome
via preload (`contextIsolation` + `sandbox`).

## Empacotamento

```bash
npm run dist:linux   # release/Maya-0.1.0.AppImage + maya-desktop_0.1.0_amd64.deb
```

## Testes

```bash
npm test      # vitest — dispatcher, stores, protocolo
npm run build # typecheck + build de produção (renderer + electron)
```

## Estrutura

```
electron/        # processo main + preload (Fase 2)
scripts/         # mock-bridge.mjs — mock do protocolo para dev
src/
  shared/        # protocol.ts (contrato com pipeline/bridge.py) + metadados
  store/         # Zustand: bridge (voz/wake/conexão), chat, níveis de áudio
  lib/           # transport (WsTransport/IpcTransport), dispatcher, singleton
  features/
    orb/         # Orb.tsx + OrbController (Three.js vanilla) + shaders GLSL
    chat/        # ChatPanel, MessageBubble, Markdown, ToolActivityCard
    wake-word/   # WakeToggle (nunca otimista: reflete só o ack do backend)
    connection/  # ConnectionStatus (o ponto vermelho do painel)
```

O orb usa **Three.js vanilla** (canvas isolado + controller imperativo):
os níveis de áudio a ~30 Hz e o estado de voz chegam ao controller via refs
(subscrições do Zustand num `useEffect`) — zero re-render por frame.
