/**
 * Mock da bridge Maya — desenvolvimento do renderer sem backend.
 *
 * Implementa o mesmo protocolo de `pipeline/bridge.py`: handshake, estado
 * inicial e os comandos `get_state`, `set_wake_word_enabled`, `ping` e
 * `send_user_message`. Além
 * disso roda uma conversa em loop com níveis de áudio a 30 Hz, para dar como
 * ver o orb reagindo e a timeline se montando sem subir Whisper/TTS.
 *
 * Uso:
 *   npm run mock          (porta 8686, default)
 *   npm run dev:web       (vite — conecta em ws://127.0.0.1:8686)
 */

import { WebSocket, WebSocketServer } from "ws";

const PORT = Number(process.env.MOCK_PORT ?? 8686);
const SPECTRUM_BINS = 32;
const LEVEL_HZ = 30;

const now = () => Date.now();

const state = {
  voice: "idle",
  wake: { enabled: true, state: "asleep", phrase: "E aí, Maya" },
  session: { appSessionId: "voice-session-mock", hermesSessionId: "hermes-session-mock" },
};

const wss = new WebSocketServer({ port: PORT });
console.log(`[mock] Maya bridge em ws://127.0.0.1:${PORT}`);

function send(socket, event) {
  if (socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ ts: now(), ...event }));
  }
}

function broadcast(event) {
  for (const client of wss.clients) send(client, event);
}

// ── Áudio sintético ────────────────────────────────────────────────────────
// Envelope de fala: rajadas rápidas em cima de uma onda lenta, para o orb ter
// ataque e silêncio de verdade em vez de um seno bonitinho.

let clock = 0;

function speechEnvelope(t) {
  const syllable = Math.pow(Math.max(0, Math.sin(t * 7.5)), 2);
  const phrase = 0.55 + 0.45 * Math.sin(t * 0.7);
  return Math.min(1, syllable * phrase * 0.9);
}

function spectrumFor(level, t) {
  const bins = new Array(SPECTRUM_BINS);
  // Formante que passeia, para os filamentos do orb não ficarem estáticos.
  const formant = 8 + Math.sin(t * 1.3) * 4;
  for (let i = 0; i < SPECTRUM_BINS; i++) {
    const distance = Math.abs(i - formant) / SPECTRUM_BINS;
    const shape = Math.exp(-distance * 6) * 0.8 + Math.pow(1 - i / SPECTRUM_BINS, 2.2) * 0.4;
    const noise = 0.85 + Math.random() * 0.3;
    bins[i] = Math.max(0, Math.min(255, Math.round(shape * noise * level * 255)));
  }
  return bins;
}

function emitLevels() {
  const speaking = state.voice === "speaking";
  const listening = state.voice === "user_speaking" || state.voice === "listening";
  const level = speaking || listening ? speechEnvelope(clock) : 0;

  const bins = spectrumFor(level, clock);
  const mean = (from, to) => {
    let sum = 0;
    for (let i = from; i < to; i++) sum += bins[i];
    return sum / (to - from) / 255;
  };

  broadcast({
    type: "audio_level",
    input: listening ? level : 0,
    output: speaking ? level : 0,
    level,
    bass: mean(0, 6),
    mid: mean(6, 18),
    treble: mean(18, SPECTRUM_BINS),
    spectrum: bins,
  });
}

setInterval(() => {
  clock += 1 / LEVEL_HZ;
  emitLevels();
}, 1000 / LEVEL_HZ);

// ── Conversa roteirizada ───────────────────────────────────────────────────

// O preâmbulo é falado ANTES da ferramenta rodar e a resposta final
// DEPOIS — mesmo turno: o renderer precisa fatiar a mensagem do agente em
// dois segmentos para manter a cronologia (texto → ferramenta → texto).
const PREAMBLE = "Vou verificar isso para você. Um instante.";
const SCRIPT = [
  { after: 1500, run: () => setVoice("user_speaking") },
  { after: 1800, run: () => setVoice("listening") },
  {
    after: 300,
    run: () => broadcast({ type: "user_transcript", text: "quantos arquivos tem no projeto?" }),
  },
  { after: 200, run: () => setVoice("thinking") },
  { after: 300, run: () => streamAgentText(PREAMBLE) },
  {
    after: 900,
    run: () =>
      broadcast({
        type: "tool_activity",
        tool: "terminal",
        label: "find . -type f | wc -l",
        emoji: "⚙",
        toolCallId: "call_mock_1",
        status: "running",
      }),
  },
  {
    after: 1400,
    run: () =>
      broadcast({
        type: "tool_activity",
        tool: "terminal",
        label: "find . -type f | wc -l",
        emoji: "⚙",
        toolCallId: "call_mock_1",
        status: "completed",
      }),
  },
  { after: 400, run: () => setVoice("speaking") },
  { after: 0, run: () => streamAgentText(REPLY) },
  { after: 4200, run: () => setVoice("idle") },
];

const REPLY = "São 1.284 arquivos, sem contar node_modules. A maior parte está em pipeline/ e desktop/src.";

let turn = 0;
let currentTurnId = "";

function streamAgentText(reply = REPLY, turnId = null) {
  const resolved = turnId ?? currentTurnId ?? `mock-turn-${++turn}`;
  if (!turnId) currentTurnId = resolved;
  const words = reply.split(" ");
  let index = 0;
  const timer = setInterval(() => {
    if (index >= words.length) {
      clearInterval(timer);
      broadcast({ type: "agent_text_end", turnId, text: REPLY });
      return;
    }
    broadcast({ type: "agent_text", turnId, delta: `${words[index++]} ` });
  }, 110);
}

// Beep curto (WAV PCM 16-bit mono) para o synthesize_word do mock.
function beepWav(seconds = 0.35, freq = 880, rate = 24000) {
  const n = Math.floor(seconds * rate);
  const data = Buffer.alloc(n * 2);
  for (let i = 0; i < n; i++) {
    const v = Math.round(Math.sin((2 * Math.PI * freq * i) / rate) * 0.2 * 32767);
    data.writeInt16LE(v, i * 2);
  }
  const header = Buffer.alloc(44);
  header.write("RIFF", 0);
  header.writeUInt32LE(36 + data.length, 4);
  header.write("WAVE", 8);
  header.write("fmt ", 12);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20); // PCM
  header.writeUInt16LE(1, 22); // mono
  header.writeUInt32LE(rate, 24);
  header.writeUInt32LE(rate * 2, 28);
  header.writeUInt16LE(2, 32);
  header.writeUInt16LE(16, 34);
  header.write("data", 36);
  header.writeUInt32LE(data.length, 40);
  return Buffer.concat([header, data]);
}

function setVoice(voice) {
  state.voice = voice;
  broadcast({ type: "state", voice, wake: state.wake });
}

async function runScript() {
  for (;;) {
    currentTurnId = ""; // cada ciclo da conversa é um turno novo
    for (const step of SCRIPT) {
      await new Promise((resolve) => setTimeout(resolve, step.after));
      if (wss.clients.size > 0) step.run();
    }
  }
}

void runScript();

// ── Conexões e comandos ────────────────────────────────────────────────────

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
    } else if (message.cmd === "synthesize_word") {
      const text = String(message.text ?? "").trim();
      if (!text) {
        send(socket, { type: "ack", id: message.id, ok: false, error: { code: "empty_text", message: "Texto vazio." } });
        return;
      }
      // Beep curto como WAV — o caminho de áudio do renderer é exercitado
      // sem depender do Kokoro (no real, o backend devolve a voz da Maya).
      send(socket, { type: "ack", id: message.id, ok: true, data: { wav: beepWav().toString("base64"), rate: 24000 } });
      console.log(`[mock] synthesize_word: ${text}`);
    } else if (message.cmd === "send_user_message") {
      const text = String(message.text ?? "").trim();
      if (!text) {
        send(socket, { type: "ack", id: message.id, ok: false, error: { code: "empty_text", message: "Mensagem vazia." } });
        return;
      }
      send(socket, { type: "ack", id: message.id, ok: true });
      broadcast({ type: "user_transcript", text });
      console.log(`[mock] mensagem do chat: ${text}`);
      // Resposta fake no mesmo fluxo do backend: pensando → falando → idle.
      setVoice("thinking");
      setTimeout(() => setVoice("speaking"), 700);
      setTimeout(() => {
        streamAgentText(`Recebi sua mensagem: "${text}". Aqui é a Maya respondendo pela caixa de texto!`);
      }, 900);
      setTimeout(() => setVoice("idle"), 4200);
    } else {
      send(socket, { type: "ack", id: message.id, ok: false, error: { code: "unknown_command", message: `Comando desconhecido: ${message.cmd}` } });
    }
  });
});
