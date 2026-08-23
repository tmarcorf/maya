/**
 * Card de atividade de ferramenta — registro de dossier.
 *
 * Duas linhas no mesmo registro: o cabeçalho (ferramenta + status) e, abaixo,
 * o detalhe do que o agente executou — para o terminal, o comando que veio
 * no `delta` do evento `hermes.tool.progress`. Sem detalhe, o card é só o
 * cabeçalho, como antes.
 */

import type { ToolActivity } from "@/store/useChatStore";

const STATUS_LABELS: Record<string, string> = {
  running: "executando",
  completed: "concluído",
  failed: "falhou",
};

export function ToolActivityCard({ activity }: { activity: ToolActivity }) {
  return (
    <div className="border border-line bg-panel px-2.5 py-1.5 font-mono text-[0.7rem] text-dim">
      <div className="flex items-center gap-2">
        <span aria-hidden="true">{activity.emoji || "▸"}</span>
        <span className="uppercase tracking-widest">{activity.tool}</span>
        {activity.status && (
          <span className="ml-auto shrink-0 uppercase tracking-widest">
            {STATUS_LABELS[activity.status] ?? activity.status}
          </span>
        )}
      </div>
      {activity.label && (
        <div
          className="mt-1 truncate border-t border-line/60 pt-1 text-text/70"
          title={activity.label}
        >
          {activity.label}
        </div>
      )}
    </div>
  );
}
