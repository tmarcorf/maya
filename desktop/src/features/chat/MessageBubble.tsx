/**
 * Bolha de mensagem.
 *
 * Usuário: à direita, texto puro sobre painel.
 * Polaris: à esquerda, marcada pelo glifo da pirâmide invertida em vermelho
 * FBC — a assinatura do painel. Markdown renderizado; durante o streaming,
 * um caret pisca no fim.
 */

import { memo } from "react";

import { Markdown } from "@/features/chat/Markdown";
import type { ChatMessage } from "@/store/useChatStore";

const timeFormat = new Intl.DateTimeFormat("pt-BR", {
  hour: "2-digit",
  minute: "2-digit",
});

export const MessageBubble = memo(function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

  return (
    <div className={isUser ? "flex flex-col items-end" : "flex flex-col items-start"}>
      <div className="mb-1 flex items-baseline gap-1.5">
        {!isUser && <span className="text-fbc" aria-hidden="true">▽</span>}
        <span className="eyebrow text-dim">
          {isUser ? "Você" : "Polaris"} · {timeFormat.format(message.ts)}
        </span>
      </div>
      <div
        className={
          isUser
            ? "max-w-[80%] border border-line bg-panel px-3 py-2 text-[0.875rem] leading-relaxed"
            : "max-w-[85%] px-0.5 text-[0.875rem] leading-relaxed"
        }
      >
        {isUser ? (
          <span className="whitespace-pre-wrap">{message.text}</span>
        ) : (
          <>
            <Markdown>{message.text}</Markdown>
            {!message.final && !message.sealed && (
              <span className="stream-caret" aria-hidden="true" />
            )}
          </>
        )}
      </div>
    </div>
  );
});
