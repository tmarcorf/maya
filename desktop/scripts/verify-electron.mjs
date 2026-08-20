import { _electron } from "playwright-core";

const app = await _electron.launch({
  executablePath: "/home/tmarcorf/Documentos/dev/polaris/desktop/node_modules/.bin/electron",
  args: ["."],
  cwd: "/home/tmarcorf/Documentos/dev/polaris/desktop",
  env: { ...process.env },
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
await win.waitForFunction(
  () => document.body.textContent?.includes("Polaris ·"),
  { timeout: 45000 },
);
console.log("[chat] mensagens espelhadas");

const info = await win.evaluate(() => ({
  estado: [...document.querySelectorAll(".eyebrow")].map((e) => e.textContent).find((t) => t.includes("Estado")),
  chat: document.querySelector(".chat-scroll")?.textContent?.slice(0, 220),
}));
console.log("[dom]", JSON.stringify(info));

// Toggle da wake word — não otimista: só muda com a confirmação do backend.
const antes = await win.evaluate(() => document.querySelector("button[aria-pressed]")?.getAttribute("aria-pressed"));
await win.click("button[aria-label]");
await win.waitForFunction(
  (prev) => document.querySelector("button[aria-pressed]")?.getAttribute("aria-pressed") !== prev,
  antes,
  { timeout: 8000 },
);
const depois = await win.evaluate(() => document.querySelector("button[aria-pressed]")?.getAttribute("aria-pressed"));
console.log(`[wake] toggle ${antes} → ${depois} (confirmado pelo mock)`);

await win.screenshot({ path: "/tmp/polaris-electron.png" });
console.log("[electron]", JSON.stringify(
  await app.evaluate(({ app: e, BrowserWindow }) => ({
    name: e.getName(), packaged: e.isPackaged, windows: BrowserWindow.getAllWindows().length,
  })),
));
console.log("[pageerrors]", errors.length ? errors : "nenhum");
await app.close();
console.log("[ok]");
