/**
 * Card de atividade de ferramenta — registro de dossier.
 */

import type { ToolActivity } from "@/store/useChatStore";

const STATUS_LABELS: Record<string, string> = {
  running: "executando",
  completed: "concluído",
  failed: "falhou",
};

export function ToolActivityCard({ activity }: { activity: ToolActivity }) {
  return (
    <div className="flex items-center gap-2 border border-line bg-panel px-2.5 py-1.5 font-mono text-[0.7rem] text-dim">
      <span aria-hidden="true">{activity.emoji || "▸"}</span>
      <span className="uppercase tracking-widest">{activity.tool}</span>
      <span className="min-w-0 flex-1 truncate text-text/70">{activity.label}</span>
      {activity.status && (
        <span className="shrink-0 uppercase tracking-widest">
          {STATUS_LABELS[activity.status] ?? activity.status}
        </span>
      )}
    </div>
  );
}
