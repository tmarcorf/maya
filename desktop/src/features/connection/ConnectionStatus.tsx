/**
 * Status da conexão com o backend — o ponto vermelho do painel.
 *
 * Aceso = bridge conectada (a "hotline" viva); pulsando = reconectando;
 * apagado = offline (o app segue aberto esperando o backend).
 */

import { useBridgeStore } from "@/store/useBridgeStore";
import type { ConnectionStatus as Status } from "@/lib/transport";

const LABELS: Record<Status, string> = {
  connected: "Conectado",
  connecting: "Conectando",
  disconnected: "Offline",
};

export function ConnectionStatus() {
  const connection = useBridgeStore((s) => s.connection);

  return (
    <div className="flex items-center gap-2" title={`Bridge: ${LABELS[connection]}`}>
      <span
        className={
          connection === "connected"
            ? "h-1.5 w-1.5 rounded-full bg-fbc"
            : connection === "connecting"
              ? "h-1.5 w-1.5 animate-pulse rounded-full bg-fbc/70"
              : "h-1.5 w-1.5 rounded-full border border-line bg-transparent"
        }
        aria-hidden="true"
      />
      <span className="eyebrow text-dim">{LABELS[connection]}</span>
    </div>
  );
}
