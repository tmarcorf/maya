/**
 * Atalho global — alterna a wake word com o app em segundo plano.
 *
 * X11 (Cinnamon) suporta `globalShortcut`; em Wayland o registro pode
 * falhar — o toggle continua disponível na janela e no tray.
 */

import { globalShortcut } from "electron";

import type { BridgeClient } from "./bridge-client";

export const WAKE_TOGGLE_ACCELERATOR = "Control+Shift+Space";

export function registerShortcuts(getBridge: () => BridgeClient | null): void {
  const ok = globalShortcut.register(WAKE_TOGGLE_ACCELERATOR, () => {
    const bridge = getBridge();
    if (!bridge) return;
    bridge
      .sendCommand({ cmd: "set_wake_word_enabled", enabled: !bridge.wake.enabled })
      .catch((error: Error) => {
        console.warn(`Atalho global: toggle da wake word falhou: ${error.message}`);
      });
  });
  if (!ok) {
    console.warn(
      `Atalho global ${WAKE_TOGGLE_ACCELERATOR} não registrado (Wayland?) — ` +
        "use o toggle na janela ou no tray.",
    );
  }
}

export function unregisterShortcuts(): void {
  globalShortcut.unregisterAll();
}
