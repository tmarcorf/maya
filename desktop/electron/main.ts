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
import { BridgeClient } from "./bridge-client";
import { registerIpcHandlers } from "./ipc";
import { registerShortcuts, unregisterShortcuts } from "./shortcuts";
import { createTray } from "./tray";

const BRIDGE_URL = process.env.BRIDGE_URL ?? "ws://127.0.0.1:8686";

let mainWindow: BrowserWindow | null = null;
let bridge: BridgeClient | null = null;
let tray: ReturnType<typeof createTray> | null = null;

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
    width: 980,
    height: 720,
    minWidth: 640,
    minHeight: 420,
    title: "Polaris — voz",
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
  });

  const devUrl = process.env.VITE_DEV_SERVER_URL;
  if (devUrl) {
    void win.loadURL(devUrl);
  } else {
    // __dirname = dist-electron/electron → ../../dist = desktop/dist (vite).
    void win.loadFile(path.join(__dirname, "../../dist/index.html"));
  }
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    bridge = new BridgeClient(BRIDGE_URL);
    bridge.on("event", (event: unknown) => broadcastToWindows("bridge:event", event));
    bridge.on("status", (status: unknown) => broadcastToWindows("bridge:status", status));

    registerIpcHandlers(() => bridge);
    registerShortcuts(() => bridge);
    createMainWindow();
    tray = createTray({
      getWindow: () => mainWindow,
      getBridge: () => bridge,
      toggleWakeWord,
      quit: () => app.quit(),
    });
    bridge.connect();

    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
      else mainWindow?.show();
    });
  });

  // Companion: fechar a janela NÃO sai do app (a bandeja continua viva).
  app.on("window-all-closed", () => {
    // no-op intencional — saída pelo tray.
  });

  app.on("will-quit", () => {
    unregisterShortcuts();
    bridge?.disconnect();
    bridge = null;
    tray?.destroy();
    tray = null;
  });
}
