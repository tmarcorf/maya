/**
 * Processo main — dono da conexão com a bridge, do tray e do atalho.
 *
 * O renderer é só um assinante do stream: os eventos chegam por IPC
 * (`bridge:event`/`bridge:status`). Com a janela fechada, o app continua
 * vivo na bandeja (companion) — sair é pelo menu do tray.
 */

import path from "node:path";

import { app, BrowserWindow } from "electron";

import { BRIDGE_VERSION } from "../src/shared/protocol";
import { BackendManager } from "./backend";
import { BridgeClient } from "./bridge-client";
import { registerIpcHandlers } from "./ipc";
import { registerShortcuts, unregisterShortcuts } from "./shortcuts";
import { createTray } from "./tray";

const BRIDGE_URL = process.env.BRIDGE_URL ?? "ws://127.0.0.1:8686";

let mainWindow: BrowserWindow | null = null;
let bridge: BridgeClient | null = null;
let backend: BackendManager | null = null;
let tray: ReturnType<typeof createTray> | null = null;
let quitting = false;

function broadcastToWindows(channel: string, payload: unknown): void {
  for (const win of BrowserWindow.getAllWindows()) {
    win.webContents.send(channel, payload);
  }
}

function toggleWakeWord(): void {
  const active = bridge;
  if (!active) return;
  active
    .sendCommand({ cmd: "set_wake_word_enabled", enabled: !active.wake.enabled })
    .catch((error: Error) => {
      console.warn(`Toggle da wake word falhou: ${error.message}`);
    });
}

function createMainWindow(): void {
  const win = new BrowserWindow({
    // Larga o bastante para o layout 60/40 lado a lado caber de saída; abaixo
    // de 768 px de largura o renderer empilha orb e conversa.
    width: 1240,
    height: 820,
    minWidth: 640,
    minHeight: 420,
    title: "Maya — voz",
    backgroundColor: "#101113",
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
    },
  });

  win.once("ready-to-show", () => win.show());
  win.on("closed", () => {
    if (mainWindow === win) mainWindow = null;
  });
  mainWindow = win;

  // A conexão no main pode amadurecer ANTES do renderer assinar os
  // listeners — sem esse snapshot, o status inicial se perderia.
  win.webContents.on("did-finish-load", () => {
    const active = bridge;
    if (!active) return;
    win.webContents.send("bridge:status", active.connectionStatus);
    if (active.session) {
      win.webContents.send("bridge:event", {
        type: "hello",
        ts: Date.now(),
        bridgeVersion: BRIDGE_VERSION,
        session: active.session,
      });
    }
    win.webContents.send("bridge:event", {
      type: "state",
      ts: Date.now(),
      voice: active.voice,
      wake: active.wake,
    });
    const backendStatus = backend?.getStatus();
    if (backendStatus) {
      win.webContents.send("backend:status", backendStatus);
    }
  });

  const devUrl = process.env.VITE_DEV_SERVER_URL;
  if (devUrl) {
    void win.loadURL(devUrl);
  } else {
    // __dirname = dist-electron/electron → ../../dist = desktop/dist (vite).
    void win.loadFile(path.join(__dirname, "../../dist/index.html"));
  }
}

// Instância única só em prod: em dev, cada `npm run dev` sobe fresco. O lock
// vive em ~/.config/Maya (userData compartilhado com o instalado) — uma
// instância anterior viva na bandeja (companion) fazia o próximo dev sair
// com exit 0 silenciosamente.
const gotLock = app.isPackaged ? app.requestSingleInstanceLock() : true;
if (!gotLock) {
  app.quit();
} else {
  if (app.isPackaged) {
    app.on("second-instance", () => {
      if (mainWindow) {
        if (mainWindow.isMinimized()) mainWindow.restore();
        mainWindow.show();
        mainWindow.focus();
      }
    });
  }

  app.whenReady().then(() => {
    bridge = new BridgeClient(BRIDGE_URL);
    bridge.on("event", (event: unknown) => broadcastToWindows("bridge:event", event));
    bridge.on("status", (status: unknown) => broadcastToWindows("bridge:status", status));

    backend = new BackendManager();
    backend.on("status", (status: unknown) => broadcastToWindows("backend:status", status));
    backend.on("status", (status: { phase: string }) => {
      // Pronto (por nós ou externo): reconecta na hora, sem esperar o backoff.
      if (status.phase === "ready" || status.phase === "external") {
        bridge?.connect();
      }
    });

    registerIpcHandlers(() => bridge, () => backend);
    registerShortcuts(() => bridge);
    createMainWindow();
    tray = createTray({
      getWindow: () => mainWindow,
      getBridge: () => bridge,
      toggleWakeWord,
      quit: () => app.quit(),
    });
    bridge.connect();
    void backend.start(); // fases fluem pelos eventos backend:status

    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
      else mainWindow?.show();
    });
  });

  // Companion: fechar a janela NÃO sai do app (a bandeja continua viva).
  app.on("window-all-closed", () => {
    // no-op intencional — saída pelo tray.
  });

  // Teardown do backend é assíncrono (SIGTERM → graça → SIGKILL): precisa
  // do preventDefault + re-quit, senão o Electron morre antes do stop().
  app.on("before-quit", (event) => {
    if (quitting || !backend) return;
    event.preventDefault();
    quitting = true;
    void backend.stop().finally(() => app.quit());
  });

  app.on("will-quit", () => {
    unregisterShortcuts();
    bridge?.disconnect();
    bridge = null;
    tray?.destroy();
    tray = null;
  });
}
