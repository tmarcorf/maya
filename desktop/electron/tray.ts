/**
 * Tray — o companion vive na bandeja mesmo com a janela fechada.
 *
 * Nota Linux: appindicator não emite cliques (só o menu de contexto) —
 * "mostrar janela" fica no menu, não em clique duplo.
 */

import path from "node:path";

import { Menu, Tray, nativeImage, type BrowserWindow } from "electron";

import { STATE_META, wakeStatusLabel } from "../src/shared/stateMeta";
import type { BridgeClient } from "./bridge-client";

export interface TrayDeps {
  getWindow: () => BrowserWindow | null;
  getBridge: () => BridgeClient | null;
  toggleWakeWord: () => void;
  quit: () => void;
}

export function createTray(deps: TrayDeps): Tray {
  // Ícone 32px (resources/tray.png); em X11 o Electron redimensiona se preciso.
  const icon = nativeImage.createFromPath(path.join(__dirname, "../resources/tray.png"));
  const tray = new Tray(icon);

  const rebuild = (): void => {
    const bridge = deps.getBridge();
    const voice = bridge?.voice ?? "idle";
    const meta = STATE_META[voice];
    const wake = bridge?.wake ?? { enabled: false, state: "disabled", phrase: null };

    tray.setToolTip(`Polaris — ${meta.label.toLowerCase()}`);
    tray.setContextMenu(
      Menu.buildFromTemplate([
        {
          label: "Mostrar janela",
          click: () => {
            const win = deps.getWindow();
            if (!win) return;
            win.show();
            win.focus();
          },
        },
        {
          label: "Wake word",
          type: "checkbox",
          checked: wake.enabled,
          sublabel: wake.enabled ? wakeStatusLabel(wake.state) : "escuta sempre",
          click: () => deps.toggleWakeWord(),
        },
        { type: "separator" },
        { label: `Estado: ${meta.label}`, enabled: false },
        { type: "separator" },
        { label: "Sair", click: () => deps.quit() },
      ]),
    );
  };

  rebuild();
  deps.getBridge()?.on("event", rebuild);
  deps.getBridge()?.on("status", rebuild);
  return tray;
}
