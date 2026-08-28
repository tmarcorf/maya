/**
 * Painel da conversa — espelho da sessão de voz.
 *
 * Mensagens e chamadas de ferramenta compartilham uma única linha do tempo
 * ordenada por `ts`, então dá para ver o que a Maya executou no ponto exato
 * do diálogo em que aconteceu.
 *
 * Auto-scroll com pin no rodapé: se o usuário rolar para cima, o painel para
 * de seguir; voltar ao fundo religa o pin. O "pensando…" aparece quando o
 * turno do agente começou e nenhum delta chegou ainda.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import { Composer } from "@/features/chat/Composer";
import { MessageBubble } from "@/features/chat/MessageBubble";
import { ToolActivityCard } from "@/features/chat/ToolActivityCard";
import { OrbGlyph } from "@/features/orb/OrbGlyph";
import { useBridgeStore } from "@/store/useBridgeStore";
import { selectTimeline, useChatStore } from "@/store/useChatStore";

export function ChatPanel() {
  const messages = useChatStore((s) => s.messages);
  const toolActivities = useChatStore((s) => s.toolActivities);
  const voice = useBridgeStore((s) => s.voice);
  const connected = useBridgeStore((s) => s.connection === "connected");

  // O merge cria um array novo; memoizar evita o loop de `getSnapshot`
  // (Zustand v5 compara por identidade) e o re-render por frame.
  const timeline = useMemo(
    () => selectTimeline({ messages, toolActivities }),
    [messages, toolActivities],
  );

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const [pinned, setPinned] = useState(true);

  useEffect(() => {
    if (pinned) bottomRef.current?.scrollIntoView({ behavior: "auto" });
  }, [timeline, pinned]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < 40);
  };

  // Volta ao final da conversa: o scroll suave chega sozinho no intervalo de
  // pin (< 40px) e o onScroll religa o `pinned` — o botão some ao chegar.
  const jumpToEnd = () => {
    const el = scrollRef.current;
    if (!el) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollTo({ top: el.scrollHeight, behavior: reduced ? "auto" : "smooth" });
  };

  const last = messages[messages.length - 1];
  // Segmentos selados (fechados por uma ferramenta) não contam como texto
  // em streaming: com a ferramenta rodando, o "pensando…" reaparece.
  const thinking =
    voice === "thinking" &&
    !(last && last.role === "agent" && !last.final && !last.sealed);

  return (
    <section className="relative flex min-h-0 flex-1 flex-col">
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="chat-scroll min-h-0 flex-1 overflow-y-auto px-4 pt-4"
      >
        {timeline.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
            <p className="eyebrow text-dim">Nenhum registro ainda</p>
            <p className="max-w-[32ch] text-sm text-dim">
              {connected
                ? "Fale com a Maya pelo microfone — a conversa aparece aqui conforme acontece."
                : "Suba o backend com ./maya.sh — o espelho conecta sozinho."}
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {timeline.map((item) =>
              item.kind === "message" ? (
                <MessageBubble key={item.id} message={item.message} />
              ) : (
                <ToolActivityCard key={item.id} activity={item.activity} />
              ),
            )}
            {thinking && (
              <div className="flex items-center gap-1.5 self-start">
                <OrbGlyph />
                <span className="eyebrow text-dim">Maya · pensando…</span>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        )}
      </div>
      {/* Pular para o final — só quando o pin soltou (usuário rolou pra cima). */}
      {!pinned && (
        <button
          type="button"
          onClick={jumpToEnd}
          className="chat-jump"
          aria-label="Pular para o final da conversa"
          title="Pular para o final da conversa"
        >
          <svg
            viewBox="0 0 24 24"
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="m6 9 6 6 6-6" />
          </svg>
        </button>
      )}
      <Composer />
    </section>
  );
}
