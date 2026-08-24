/**
 * Reprodução controlada: bridge WS própria (porta 8688) emite uma resposta
 * longa COM espaços, e o script descreve o layout das bolhas.
 */
import { _electron } from "playwright-core";
import { WebSocketServer, WebSocket } from "ws";

const PORT = 8688;
const ROOT = "/home/tmarcorf/Documentos/dev/polaris/desktop";

const now = () => Date.now();
const clients = new Set();

const wss = new WebSocketServer({ port: PORT });
wss.on("connection", (socket) => {
  clients.add(socket);
  socket.send(JSON.stringify({ ts: now(), type: "hello", bridgeVersion: 1, session: { appSessionId: "s", hermesSessionId: "h" } }));
  socket.send(JSON.stringify({ ts: now(), type: "state", voice: "idle", wake: { enabled: true, state: "asleep", phrase: "E aí, Polaris" } }));
  socket.on("message", (raw) => {
    let msg;
    try { msg = JSON.parse(String(raw)); } catch { return; }
    if (msg.cmd === "get_state") {
      socket.send(JSON.stringify({ ts: now(), type: "ack", id: msg.id, ok: true, data: { voice: "idle", wake: { enabled: true, state: "asleep", phrase: "E aí, Polaris" }, session: { appSessionId: "s", hermesSessionId: "h" } } }));
    } else if (msg.cmd === "ping") {
      socket.send(JSON.stringify({ ts: now(), type: "ack", id: msg.id, ok: true, data: "pong" }));
    } else {
      socket.send(JSON.stringify({ ts: now(), type: "ack", id: msg.id, ok: true }));
    }
  });
  socket.on("close", () => clients.delete(socket));
});
const broadcast = (event) => {
  const frame = JSON.stringify({ ts: now(), ...event });
  for (const c of clients) if (c.readyState === WebSocket.OPEN) c.send(frame);
};

const app = await _electron.launch({
  executablePath: `${ROOT}/node_modules/.bin/electron`,
  args: [".", "--user-data-dir=/tmp/polaris-repro2"],
  cwd: ROOT,
  env: { ...process.env, VITE_DEV_SERVER_URL: "http://127.0.0.1:5174" },
});
const win = await app.firstWindow();
await win.waitForLoadState("domcontentloaded");
await win.waitForTimeout(2500); // deixa a mãozinha conectar

// Turno do agente: deltas com espaços normais, como o backend real envia.
const TURN = "turn-repro-1";
const REPLY = "A Polaris está de pé e operacional. Todos os sistemas funcionando normalmente, sem nenhuma anomalia registrada no dia de hoje.";
const words = REPLY.split(" ");
for (let i = 0; i < words.length; i++) {
  broadcast({ type: "agent_text", turnId: TURN, delta: `${words[i]} ` });
  await new Promise((r) => setTimeout(r, 90));
}
broadcast({ type: "agent_text_end", turnId: TURN, text: REPLY });
await win.waitForTimeout(1500);

const state = await win.evaluate(() => {
  const bubbles = [...document.querySelectorAll(".markdown-body")];
  const container = document.querySelector(".chat-scroll");
  const containerRect = container?.getBoundingClientRect();
  const panel = container?.querySelector(".flex.flex-col.gap-3") ?? container?.firstElementChild;
  const panelRect = panel?.getBoundingClientRect();
  return {
    containerWidth: containerRect ? `${containerRect.width}px` : null,
    panelWidth: panelRect ? `${panelRect.width}px` : null,
    bubbles: bubbles.map((el) => {
      const r = el.getBoundingClientRect();
      const p = el.querySelector("p");
      const pr = p?.getBoundingClientRect();
      return {
        text: el.textContent?.slice(0, 60),
        width: `${r.width}px`,
        scrollWidth: el.scrollWidth,
        clientWidth: el.clientWidth,
        overflows: el.scrollWidth > el.clientWidth + 1,
        pWidth: pr ? `${pr.width}px` : null,
        pScrollWidth: p ? p.scrollWidth : null,
        pOverflows: p ? p.scrollWidth > p.clientWidth + 1 : null,
        lineHeight: p ? getComputedStyle(p).lineHeight : null,
      };
    }),
  };
});
console.log(JSON.stringify(state, null, 2));
await win.screenshot({ path: "/tmp/polaris-chat2.png" });
console.log("[screenshot] /tmp/polaris-chat2.png");
await app.close();
wss.close();
process.exit(0);
