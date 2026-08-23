import { useEffect, useState } from "react";

import { ChatPanel } from "@/features/chat/ChatPanel";
import { ConnectionStatus } from "@/features/connection/ConnectionStatus";
import { OrbStage } from "@/features/orb/OrbStage";
import { OscilloscopeStage } from "@/features/orb/OscilloscopeStage";
import { SettingsButton, SettingsPanel } from "@/features/settings/SettingsPanel";
import { initBridge } from "@/lib/dispatcher";
import { wakeStatusLabel } from "@/shared/stateMeta";
import { useBridgeStore } from "@/store/useBridgeStore";
import { hydrateChatHistory } from "@/store/useChatStore";
import { useOrbSettingsStore } from "@/store/useOrbSettingsStore";

/**
 * Painel de instrumentos — o orb ocupa 60% da largura, o registro da conversa
 * os 40% restantes. Abaixo de `lg` os dois empilham, senão a conversa vira
 * uma faixa ilegível.
 */
export default function App() {
  useEffect(() => {
    hydrateChatHistory();
    return initBridge();
  }, []);
  const wake = useBridgeStore((s) => s.wake);
  const session = useBridgeStore((s) => s.session);
  const palette = useOrbSettingsStore((s) => s.palette);
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <div className="app-root flex h-full flex-col md:flex-row" data-palette={palette}>
      {/* Palco do orb: canvas em tela cheia do painel, HUD sobreposto. */}
      <section className="orb-stage relative h-[42vh] min-h-[220px] shrink-0 overflow-hidden md:h-auto md:min-h-0 md:w-0 md:flex-[3]">
        <div className="absolute inset-0">
          <OrbStage />
        </div>
        {/* Traço de áudio da Polaris, sob o orb — visível só quando ela fala. */}
        <OscilloscopeStage />
        <div className="orb-hud">
          {session?.appSessionId && (
            <div className="orb-meta eyebrow hidden text-dim/60 md:block">
              Wake Word - {wake.enabled ? wakeStatusLabel(wake.state) : "desligado"}
              {wake.enabled && wake.phrase ? ` — “${wake.phrase}”` : ""}
            </div>
          )}
        </div>
      </section>

      {/* Conversa: transcrição, resposta em streaming e ações do Hermes.
          Sem divisor nem borda: o fundo é o mesmo da paleta do orb. */}
      <section className="palette-bg flex min-h-0 flex-1 flex-col md:w-0 md:flex-[2]">
        <header className="flex shrink-0 items-center justify-between gap-3 px-4 py-3">
          <span className="eyebrow text-text">Conversa</span>
          <div className="flex items-center gap-3">
            <ConnectionStatus />
            <SettingsButton onClick={() => setSettingsOpen(true)} />
          </div>
        </header>
        <ChatPanel />
      </section>

      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
