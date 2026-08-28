/**
 * Ciclo de vida do backend Python, gerenciado pelo processo main.
 *
 * Canal separado do protocolo da bridge de propósito: o protocolo da bridge
 * espelha `pipeline/bridge.py` 1:1 (contrato entre processos), enquanto este
 * contrato é uma preocupação local do desktop — spawn, monitoramento e
 * encerramento do processo de voz.
 */

export type BackendPhase =
  | "starting" // spawn em andamento
  | "ready" // porta da bridge abriu, nós spawnamos
  | "external" // porta já estava aberta — reutilizando
  | "failed" // spawn/health/config falhou (detail explica)
  | "skipped" // MAYA_SKIP_BACKEND=1 — backend não gerenciado
  | "stopped"; // encerrado no quit

export interface BackendStatus {
  phase: BackendPhase;
  /** PT-BR, legível — instruções quando `failed`. */
  detail?: string;
  pid?: number;
  exitCode?: number | null;
  /** Últimas ~8 KB do log relevante (backend/hermes). */
  logTail?: string;
  /** Caminho absoluto do log no userData. */
  logFile?: string;
}
