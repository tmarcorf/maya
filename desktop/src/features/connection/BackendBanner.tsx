/**
 * Banner do ciclo de vida do backend — o erro deixa de ser um tooltip de uma
 * linha e vira aviso na tela.
 *
 * Vermelho quando o backend falhou (detail + caminho do log + tail rolante
 * em <details>); fino/neutro enquanto inicia com detalhe; aviso discreto
 * quando não é gerenciado (MAYA_SKIP_BACKEND=1) — este só quando a bridge
 * também não responde, senão vira ruído com um backend externo na porta.
 *
 * Some sozinho quando a fase muda; sem botão de dismiss.
 */

import { useBackendStore } from "@/store/useBackendStore";
import { useBridgeStore } from "@/store/useBridgeStore";

export function BackendBanner() {
  const phase = useBackendStore((s) => s.phase);
  const detail = useBackendStore((s) => s.detail);
  const logFile = useBackendStore((s) => s.logFile);
  const logTail = useBackendStore((s) => s.logTail);
  const connection = useBridgeStore((s) => s.connection);

  if (phase === "failed") {
    return (
      <div className="pointer-events-none fixed inset-x-0 top-3 z-50 flex justify-center px-4">
        <div
          role="alert"
          className="pointer-events-auto w-full max-w-md rounded-md border border-fbc/40 bg-panel/95 p-3 shadow-lg"
        >
          <span className="eyebrow text-fbc">Backend falhou</span>
          {detail && <p className="mt-1 text-[0.8rem] leading-snug text-text">{detail}</p>}
          {logFile && (
            <p className="mt-1 break-all font-mono text-[0.7rem] text-dim">Log: {logFile}</p>
          )}
          {logTail && (
            <details className="mt-2">
              <summary className="cursor-pointer text-[0.7rem] text-dim">Ver últimas linhas</summary>
              <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[0.7rem] text-dim">
                {logTail}
              </pre>
            </details>
          )}
        </div>
      </div>
    );
  }

  if (phase === "starting" && detail) {
    return (
      <div className="pointer-events-none fixed inset-x-0 top-3 z-50 flex justify-center px-4">
        <div className="pointer-events-auto flex items-center gap-2 rounded-md border border-line bg-panel/90 px-3 py-2 shadow">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-fbc/70" aria-hidden="true" />
          <span className="eyebrow text-dim">Iniciando backend…</span>
          {detail && <span className="text-[0.7rem] text-dim">{detail}</span>}
        </div>
      </div>
    );
  }

  if (phase === "skipped" && connection !== "connected" && detail) {
    return (
      <div className="pointer-events-none fixed inset-x-0 top-3 z-50 flex justify-center px-4">
        <div className="pointer-events-auto flex items-center gap-2 rounded-md border border-line bg-panel/90 px-3 py-2 shadow">
          <span className="eyebrow text-dim">Backend não gerenciado</span>
          <span className="text-[0.7rem] text-dim">{detail}</span>
        </div>
      </div>
    );
  }

  return null;
}
