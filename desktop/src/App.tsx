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
 *
 * A conversa é recolhível para a lateral direita ("»" no topo do painel): o
 * palco do orb se expande no lugar e uma aba fina na borda direita traz a
 * conversa de volta ("«"). O painel permanece montado — só a geometria muda —
 * então histórico, scroll e streaming continuam vivos.
 */

function ChevronIcon({ direction }: { direction: "left" | "right" }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-3.5 w-3.5"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={direction === "left" ? "M15 18l-6-6 6-6" : "M9 18l6-6-6-6"} />
    </svg>
  );
}

export default function App() {
  useEffect(() => {
    hydrateChatHistory();
    return initBridge();
  }, []);
  const wake = useBridgeStore((s) => s.wake);
  const session = useBridgeStore((s) => s.session);
  const palette = useOrbSettingsStore((s) => s.palette);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(true);

  return (
    <div className="app-root flex h-full flex-col md:flex-row" data-palette={palette}>
      {/* Palco do orb: canvas em tela cheia do painel, HUD sobreposto.
          Com a conversa recolhida, a aba "«" na borda direita reabre o painel. */}
      <section
        className={`orb-stage relative min-h-[220px] shrink-0 overflow-hidden md:h-auto md:min-h-0 md:w-0 md:flex-[3] ${
          chatOpen ? "h-[42vh]" : "h-full"
        }`}
      >
        <div className="absolute inset-0">
          <OrbStage />
        </div>
        {/* Traço de áudio da Maya, sob o orb — visível só quando ela fala. */}
        <OscilloscopeStage />
        <div className="orb-hud">
          {session?.appSessionId && (
            <div className="orb-meta eyebrow hidden text-dim/60 md:block">
              Wake Word - {wake.enabled ? wakeStatusLabel(wake.state) : "desligado"}
              {wake.enabled && wake.phrase ? ` — “${wake.phrase}”` : ""}
            </div>
          )}
        </div>
        {!chatOpen && (
          <button
            type="button"
            onClick={() => setChatOpen(true)}
            aria-expanded={chatOpen}
            aria-label="Exibir conversa"
            title="Exibir conversa"
            className="absolute right-0 top-1/2 z-10 -translate-y-1/2 border border-l-0 border-line bg-panel p-2 text-dim transition-colors hover:border-text/40 hover:text-text"
          >
            <ChevronIcon direction="left" />
          </button>
        )}
      </section>

      {/* Conversa: transcrição, resposta em streaming e ações do Hermes.
          Sem divisor nem borda: o fundo é o mesmo da paleta do orb.
          Recolhida, desliza para a direita (md+: largura 0; empilhado: altura 0). */}
      <section
        aria-hidden={!chatOpen}
        inert={!chatOpen}
        className={`palette-bg flex min-h-0 flex-1 flex-col transition-all duration-300 ease-in-out md:min-w-0 md:w-0 ${
          chatOpen
            ? "max-h-full opacity-100 md:max-h-none md:flex-[2]"
            : "max-h-0 overflow-hidden opacity-0 md:max-h-none md:max-w-0 md:flex-[0]"
        }`}
      >
        <header className="flex shrink-0 items-center justify-between gap-3 px-4 py-3">
          <span className="eyebrow text-text">Conversa</span>
          <div className="flex items-center gap-3">
            <ConnectionStatus />
            <SettingsButton onClick={() => setSettingsOpen(true)} />
            <button
              type="button"
              onClick={() => setChatOpen(false)}
              aria-expanded={chatOpen}
              aria-label="Recolher conversa"
              title="Recolher conversa"
              className="border border-line bg-panel p-1.5 text-dim transition-colors hover:border-text/40 hover:text-text"
            >
              <ChevronIcon direction="right" />
            </button>
          </div>
        </header>
        <ChatPanel />
      </section>

      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
