/**
 * Mock da bridge Polaris — desenvolvimento do renderer sem backend.
 *
 * Implementa o mesmo protocolo de `pipeline/bridge.py` e roda uma cena
 * scriptada em loop: idle → escuta → fala do usuário (níveis de mic) →
 * transcrição → pensando (com tool) → streaming de texto → fala da
 * Polaris (níveis de TTS) → idle.
 *
 * Uso:
 *   npm run mock          (porta 8686, default)
 *   npm run dev:web       (vite — conecta em ws://127.0.0.1:8686)
 */

import { WebSocket, WebSocketServer } from "ws";

const PORT = Number(process.env.MOCK_PORT ?? 8686);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const now = () => Date.now();

const state = {
  voice: "idle",
  wake: { enabled: true, state: "asleep", phrase: "E aí, Polaris" },
  session: { appSessionId: "voice-session-mock", hermesSessionId: "hermes-session-mock" },
};

const wss = new WebSocketServer({ port: PORT });
console.log(`[mock] Polaris bridge em ws://127.0.0.1:${PORT}`);

function send(socket, event) {
  if (socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ ts: now(), ...event }));
  }
}

function broadcast(event) {
  for (const client of wss.clients) send(client, event);
}

function setVoice(voice) {
  if (voice === state.voice) return;
  state.voice = voice;
  broadcast({ type: "state", voice, wake: state.wake });
}

wss.on("connection", (socket) => {
  console.log("[mock] client conectado");
  send(socket, { type: "hello", bridgeVersion: 1, session: state.session });
  send(socket, { type: "state", voice: state.voice, wake: state.wake });

  socket.on("message", (raw) => {
    let message;
    try {
      message = JSON.parse(String(raw));
    } catch {
      send(socket, { type: "ack", id: null, ok: false, error: { code: "bad_json", message: "JSON inválido." } });
      return;
    }
    if (message.cmd === "get_state") {
      send(socket, { type: "ack", id: message.id, ok: true, data: { ...state } });
    } else if (message.cmd === "set_wake_word_enabled") {
      state.wake.enabled = Boolean(message.enabled);
      state.wake.state = state.wake.enabled ? "asleep" : "disabled";
      send(socket, { type: "ack", id: message.id, ok: true, data: { enabled: state.wake.enabled } });
      broadcast({ type: "wake_state", ...state.wake });
      console.log(`[mock] wake word ${state.wake.enabled ? "ativada" : "desativada"}`);
    } else if (message.cmd === "ping") {
      send(socket, { type: "ack", id: message.id, ok: true, data: "pong" });
    } else {
      send(socket, { type: "ack", id: message.id, ok: false, error: { code: "unknown_command", message: `Comando desconhecido: ${message.cmd}` } });
    }
  });
});

/** Níveis de áudio sintéticos em ~30 Hz (0 → pico → 0). */
async function playLevels(channel, durationMs) {
  const steps = Math.max(1, Math.round(durationMs / 33));
  for (let i = 0; i < steps; i++) {
    const envelope = Math.sin((Math.PI * i) / steps); // sobe e desce
    const level = Math.max(0, envelope * (0.35 + 0.35 * Math.random()));
    broadcast({ type: "audio_level", input: channel === "input" ? level : 0, output: channel === "output" ? level : 0 });
    await sleep(33);
  }
  broadcast({ type: "audio_level", input: 0, output: 0 });
}

/** Um turno completo de conversa. */
async function exchange(question, answerDeltas, withTool = false) {
  setVoice("listening");
  await sleep(900);

  setVoice("user_speaking");
  await playLevels("input", 1400);
  broadcast({ type: "user_transcript", text: question });
  setVoice("listening");
  await sleep(600);

  setVoice("thinking");
  const turnId = `turn-mock-${now()}`;
  if (withTool) {
    const toolCallId = `call-mock-${now()}`;
    broadcast({ type: "tool_activity", tool: "terminal", label: "date +%H:%M", emoji: "▸", toolCallId, status: "running" });
    await sleep(700);
    broadcast({ type: "tool_activity", tool: "terminal", label: "date +%H:%M", emoji: "▸", toolCallId, status: "completed" });
    await sleep(500);
  }
  for (const delta of answerDeltas) {
    broadcast({ type: "agent_text", turnId, delta });
    await sleep(90 + Math.random() * 120);
  }
  broadcast({ type: "agent_text_end", turnId, text: answerDeltas.join("") });

  setVoice("speaking");
  await playLevels("output", answerDeltas.join("").length * 55);
  setVoice("idle");
  await sleep(2600);
}

const EXCHANGES = [
  [
    "Que horas são?",
    ["São", " **14h32**", ", no", " fuso", " de", " Brasília", "."],
    true,
  ],
  [
    "Me mostra um exemplo de código em Python",
    [
      "Claro. Um", " exemplo", " rápido:\n\n",
      "```python\nprint(\"Olá, Polaris\")\n```\n\n",
      "- Fica", " à vontade", " para", " testar",
      "\n- E", " me perguntar", " qualquer", " coisa",
    ],
    false,
  ],
  [
    "O que você é?",
    [
      "Sou a", " Polaris", " — sua", " bússola", " local.",
      " Tudo", " roda", " nesta", " máquina", ".",
    ],
    false,
  ],
];

async function scene() {
  let index = 0;
  for (;;) {
    const [question, deltas, withTool] = EXCHANGES[index % EXCHANGES.length];
    index += 1;
    await exchange(question, deltas, withTool);
  }
}

scene();
