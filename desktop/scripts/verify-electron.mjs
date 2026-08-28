/**
 * Verificação end-to-end do app contra o mock da bridge.
 *
 * Sobe o Electron, espera a conexão e a conversa roteirizada do mock, e
 * confere o que o usuário veria: orb renderizando, timeline com mensagens e
 * ações de ferramenta, e a gaveta de ajustes operando.
 *
 * Uso:  npm run mock &  &&  node scripts/verify-electron.mjs
 */

import { _electron } from "playwright-core";

const ROOT = new URL("..", import.meta.url).pathname;

const app = await _electron.launch({
  executablePath: `${ROOT}node_modules/.bin/electron`,
  // userData próprio: o lock de instância única é por perfil, então a
  // verificação roda sem derrubar um app aberto — e sem tocar no histórico real.
  args: [".", "--user-data-dir=/tmp/maya-verify"],
  cwd: ROOT,
  // O e2e testa contra o mock da bridge: o app não pode spawnar o backend real.
  env: { ...process.env, MAYA_SKIP_BACKEND: "1" },
});
const win = await app.firstWindow();
const errors = [];
win.on("pageerror", (err) => errors.push(err.message));
await win.waitForLoadState("domcontentloaded");
console.log("[title]", JSON.stringify(await win.title()));

await win.waitForFunction(
  () => document.querySelector('[title^="Bridge"]')?.textContent?.includes("Conectado"),
  { timeout: 20000 },
);
console.log("[conexão] Conectado");

// O mock roteiriza: transcrição → ferramenta → resposta em streaming.
await win.waitForFunction(
  () => document.querySelector(".chat-scroll")?.textContent?.includes("quantos arquivos"),
  { timeout: 30000 },
);
console.log("[chat] transcrição do usuário espelhada");

// `uppercase` é só CSS: o textContent continua minúsculo.
await win.waitForFunction(
  () => document.querySelector(".chat-scroll")?.textContent?.includes("terminal"),
  { timeout: 30000 },
);
console.log("[chat] ação de ferramenta exibida");

await win.waitForFunction(
  () => document.querySelector(".chat-scroll")?.textContent?.includes("concluído"),
  { timeout: 30000 },
);
console.log("[chat] ferramenta concluída");

// A ferramenta precisa ficar ancorada entre as mensagens, não no fim da lista.
const ordem = await win.evaluate(() => {
  const scroll = document.querySelector(".chat-scroll");
  if (!scroll) return [];
  return [...scroll.querySelectorAll(":scope > div > *")].map((el) =>
    el.className.includes("font-mono") ? "tool" : "msg",
  );
});
console.log("[timeline]", JSON.stringify(ordem));

// O orb é WebGL: a prova de vida é o canvas ter tamanho real e o palco não
// estar uniformemente preto no screenshot.
const canvas = await win.evaluate(() => {
  const el = document.querySelector("canvas");
  return el ? { w: el.width, h: el.height, cw: el.clientWidth, ch: el.clientHeight } : null;
});
console.log("[orb] canvas", JSON.stringify(canvas));

const stage = win.locator(".orb-stage");
await stage.screenshot({ path: "/tmp/maya-orb-a.png" });
await win.waitForTimeout(400);
await stage.screenshot({ path: "/tmp/maya-orb-b.png" });
// Dois quadros idênticos byte a byte significariam orb congelado.
const [a, b] = await Promise.all([
  import("node:fs").then((fs) => fs.readFileSync("/tmp/maya-orb-a.png")),
  import("node:fs").then((fs) => fs.readFileSync("/tmp/maya-orb-b.png")),
]);
console.log(
  `[orb] anima: ${a.equals(b) ? "NÃO (quadros idênticos)" : "sim"} (${a.length} vs ${b.length} bytes)`,
);

// Proporção 60/40 na horizontal.
const layout = await win.evaluate(() => {
  const orb = document.querySelector(".orb-stage");
  const chat = document.querySelector(".chat-scroll")?.closest("section");
  if (!orb || !chat) return null;
  const a = orb.getBoundingClientRect();
  const b = chat.getBoundingClientRect();
  return { orb: Math.round(a.width), chat: Math.round(b.width), ratio: +(a.width / (a.width + b.width)).toFixed(3) };
});
console.log("[layout]", JSON.stringify(layout));

// Ajustes: abrir a gaveta, trocar paleta e alternar a wake word.
await win.click('button[aria-label="Abrir ajustes"]');
await win.waitForSelector('aside[role="dialog"]', { timeout: 5000 });
console.log("[ajustes] gaveta aberta");

const antes = await win.evaluate(
  () => document.querySelector('aside button[aria-label^="Desativar"], aside button[aria-label^="Ativar"]')?.getAttribute("aria-pressed"),
);
await win.click('aside button[aria-label^="Desativar"], aside button[aria-label^="Ativar"]');
await win.waitForFunction(
  (prev) =>
    document
      .querySelector('aside button[aria-label^="Desativar"], aside button[aria-label^="Ativar"]')
      ?.getAttribute("aria-pressed") !== prev,
  antes,
  { timeout: 8000 },
);
const depois = await win.evaluate(
  () => document.querySelector('aside button[aria-label^="Desativar"], aside button[aria-label^="Ativar"]')?.getAttribute("aria-pressed"),
);
console.log(`[wake] toggle ${antes} → ${depois} (confirmado pelo mock)`);

await win.click('button[title="Magma"]');
const paleta = await win.evaluate(
  () => document.querySelector('button[title="Magma"]')?.getAttribute("aria-pressed"),
);
console.log("[ajustes] paleta Magma aria-pressed =", paleta);

// A gravação é throttled em 250 ms para não escrever a cada frame do slider.
await win.waitForTimeout(600);
const persistido = await win.evaluate(() => localStorage.getItem("maya.orb-settings.v1"));
console.log("[ajustes] persistido:", persistido);

await win.keyboard.press("Escape");
await win.waitForFunction(() => !document.querySelector('aside[role="dialog"]'), { timeout: 5000 });
console.log("[ajustes] fecha com Esc");

await win.screenshot({ path: "/tmp/maya-electron.png" });
console.log(
  "[electron]",
  JSON.stringify(
    await app.evaluate(({ app: e, BrowserWindow }) => ({
      name: e.getName(),
      packaged: e.isPackaged,
      windows: BrowserWindow.getAllWindows().length,
    })),
  ),
);
console.log("[pageerrors]", errors.length ? errors : "nenhum");
await app.close();
console.log("[ok]");
