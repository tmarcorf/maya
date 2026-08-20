import { useEffect } from "react";

import { ChatPanel } from "@/features/chat/ChatPanel";
import { ConnectionStatus } from "@/features/connection/ConnectionStatus";
import { Orb } from "@/features/orb/Orb";
import { WakeToggle } from "@/features/wake-word/WakeToggle";
import { initBridge } from "@/lib/dispatcher";
import { STATE_META, wakeStatusLabel } from "@/shared/stateMeta";
import { useBridgeStore } from "@/store/useBridgeStore";
import { hydrateChatHistory } from "@/store/useChatStore";

/**
 * Painel de instrumentos — header com a identidade FBC, orb central com
 * readout de estado e o registro da conversa abaixo.
 */
export default function App() {
  useEffect(() => {
    hydrateChatHistory();
    return initBridge();
  }, []);
  const voice = useBridgeStore((s) => s.voice);
  const wake = useBridgeStore((s) => s.wake);
  const session = useBridgeStore((s) => s.session);

  const meta = STATE_META[voice];

  return (
    <div className="flex h-full flex-col">
      <header className="flex shrink-0 items-center justify-between gap-4 border-b border-line px-4 py-3">
        <div className="flex items-baseline gap-3">
          <span className="eyebrow text-text">◤ Polaris</span>
          <span className="eyebrow hidden text-dim sm:inline">companion de voz</span>
        </div>
        <div className="flex items-center gap-4">
          <ConnectionStatus />
          <WakeToggle />
        </div>
      </header>

      <main className="flex min-h-0 flex-1 flex-col">
        <section className="relative flex h-[38vh] min-h-[200px] shrink-0 items-center justify-center">
          <div className="absolute inset-0">
            <Orb />
          </div>
          <div className="pointer-events-none absolute inset-x-0 bottom-3 flex flex-col items-center gap-1.5">
            <div className="eyebrow flex items-center gap-2" style={{ color: meta.color }}>
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
              Estado: {meta.label}
            </div>
            <div className="eyebrow text-dim">
              Wake word:{" "}
              <span className={wake.enabled ? "text-state-listening" : ""}>
                {wake.enabled ? wakeStatusLabel(wake.state) : "desligado"}
              </span>
              {wake.enabled && wake.phrase ? ` — “${wake.phrase}”` : ""}
            </div>
            {session?.appSessionId && (
              <div className="eyebrow text-dim/60">
                {session.appSessionId}
                {session.hermesSessionId ? ` · ${session.hermesSessionId}` : ""}
              </div>
            )}
          </div>
        </section>

        <div className="h-px shrink-0 bg-line" />

        <ChatPanel />
      </main>
    </div>
  );
}
