/**
 * IPC main ↔ renderer — a única porta do renderer para o processo main.
 *
 * `bridge:command` valida o sender (só a nossa janela, em dev ou prod) e
 * encaminha ao BridgeClient; `history:*` espelha o histórico no userData.
 */

import { ipcMain, type IpcMainInvokeEvent } from "electron";

import type { Command } from "../src/shared/protocol";
import type { BridgeClient } from "./bridge-client";
import { clearHistory, loadHistory, saveHistory } from "./history-store";

const KNOWN_COMMANDS = new Set(["get_state", "set_wake_word_enabled", "ping"]);

function isTrustedSender(event: IpcMainInvokeEvent): boolean {
  const url = event.senderFrame?.url ?? "";
  return url.startsWith("file://") || url.startsWith("http://127.0.0.1:517");
}

export function registerIpcHandlers(getBridge: () => BridgeClient | null): void {
  ipcMain.handle("bridge:get-state", (event) => {
    if (!isTrustedSender(event)) throw new Error("Sender não confiável.");
    const bridge = getBridge();
    return {
      status: bridge?.connectionStatus ?? "disconnected",
      session: bridge?.session ?? null,
      voice: bridge?.voice ?? "idle",
      wake: bridge?.wake ?? { enabled: false, state: "disabled", phrase: null },
    };
  });

  ipcMain.handle("bridge:command", async (event, command: unknown) => {
    if (!isTrustedSender(event)) {
      throw new Error("IPC bridge:command de um sender não confiável.");
    }
    const bridge = getBridge();
    if (!bridge) {
      throw new Error("Bridge indisponível.");
    }
    if (
      typeof command !== "object" ||
      command === null ||
      typeof (command as Command).cmd !== "string" ||
      !KNOWN_COMMANDS.has((command as Command).cmd)
    ) {
      throw new Error("Comando desconhecido.");
    }
    return bridge.sendCommand(command as Omit<Command, "id">);
  });

  ipcMain.handle("history:load", (event) => {
    if (!isTrustedSender(event)) throw new Error("Sender não confiável.");
    return loadHistory();
  });

  ipcMain.handle("history:save", (event, messages: unknown) => {
    if (!isTrustedSender(event)) throw new Error("Sender não confiável.");
    if (!Array.isArray(messages)) throw new Error("Histórico inválido.");
    saveHistory(messages as Parameters<typeof saveHistory>[0]);
    return undefined;
  });

  ipcMain.handle("history:clear", (event) => {
    if (!isTrustedSender(event)) throw new Error("Sender não confiável.");
    clearHistory();
    return undefined;
  });
}
