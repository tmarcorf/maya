/**
 * Status da conexão com o backend — o ponto vermelho do painel.
 *
 * Aceso = bridge conectada (a "hotline" viva); pulsando = reconectando;
 * apagado = offline (o app segue aberto esperando o backend).
 *
 * O ciclo de vida do backend (main) aparece aqui só quando não está
 * silenciosamente ok: "Iniciando backend…" durante o spawn e "Backend
 * falhou" com tooltip do motivo + caminho do log.
 */

import type { ConnectionStatus as Status } from "@/lib/transport";
import { useBackendStore } from "@/store/useBackendStore";
import { useBridgeStore } from "@/store/useBridgeStore";

const LABELS: Record<Status, string> = {
  connected: "Conectado",
  connecting: "Conectando",
  disconnected: "Offline",
};

export function ConnectionStatus() {
  const connection = useBridgeStore((s) => s.connection);
  const backendPhase = useBackendStore((s) => s.phase);
  const backendDetail = useBackendStore((s) => s.detail);
  const backendLogFile = useBackendStore((s) => s.logFile);

  const backendTooltip = [backendDetail, backendLogFile && `Log: ${backendLogFile}`]
    .filter(Boolean)
    .join("\n");

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
      {backendPhase === "starting" && (
        <span className="eyebrow animate-pulse text-dim" title={backendTooltip || undefined}>
          Iniciando backend…
        </span>
      )}
      {backendPhase === "failed" && (
        <span className="eyebrow text-fbc" title={backendTooltip}>
          Backend falhou
        </span>
      )}
    </div>
  );
}
