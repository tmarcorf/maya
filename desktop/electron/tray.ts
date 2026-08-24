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

  // O menu só exibe `voice` (tooltip + "Estado:") e `wake` — nada disso muda
  // com `audio_level` (30 Hz). Reconstruir `Menu.buildFromTemplate` a cada
  // evento era o grosso do custo do main em idle: o dedupe por chave + o
  // debounce de 200 ms derrubam ~30 rebuilds/s para ~0 quando nada muda.
  let lastKey = "";
  let pending: NodeJS.Timeout | null = null;

  const menuKey = (): string => {
    const bridge = deps.getBridge();
    const wake = bridge?.wake ?? { enabled: false, state: "disabled" };
    return `${bridge?.voice ?? "idle"}|${wake.enabled}|${wake.state}`;
  };

  const rebuild = (): void => {
    if (menuKey() === lastKey) return; // nada exibido mudou
    lastKey = menuKey();
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

  const schedule = (): void => {
    if (pending) return;
    pending = setTimeout(() => {
      pending = null;
      rebuild();
    }, 200);
  };

  rebuild();
  deps.getBridge()?.on("event", (event) => {
    // `state` e `wake_state` são os únicos que alteram o menu; os demais
    // (audio_level incluído) são ignorados sem nem agendar.
    if (event.type === "state" || event.type === "wake_state") schedule();
  });
  deps.getBridge()?.on("status", schedule); // conexão: o dedupe cobre redundâncias
  return tray;
}
