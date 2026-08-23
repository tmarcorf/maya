/**
 * Caixa de texto do chat — digitar além de falar.
 *
 * O texto enviado vai pelo comando `send_user_message`: o backend injeta a
 * mensagem no pipeline (ignorando a wake word), a Polaris responde por voz
 * e a resposta aparece no chat pelos eventos existentes. A bolha do usuário
 * nasce do `user_transcript` ecoado pelo backend — nunca otimista, padrão
 * do espelho.
 *
 * Enter (ou o botão de enviar) manda; Shift+Enter quebra linha; composição
 * IME não envia.
 */

function SendIcon() {
  return (
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
      <path d="M5 12h14" />
      <path d="m12 5 7 7-7 7" />
    </svg>
  );
}

import { useRef, useState } from "react";

import { transport } from "@/lib/bridge";
import { useBridgeStore } from "@/store/useBridgeStore";

const MAX_LINES = 3;
const MAX_LENGTH = 2000;
// text-[0.875rem] com line-height 1.5 = 21px por linha; + py-2 (16px).
const MAX_HEIGHT = MAX_LINES * 21 + 16;

export function Composer() {
  const connected = useBridgeStore((s) => s.connection === "connected");
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const ref = useRef<HTMLTextAreaElement | null>(null);

  // Auto-resize: cresce até MAX_LINES, depois rola internamente.
  const resize = (el: HTMLTextAreaElement) => {
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
  };

  const send = async () => {
    const value = text.trim();
    if (!value || sending || !connected) return;
    setSending(true);
    try {
      const ack = await transport.sendCommand({
        cmd: "send_user_message",
        text: value,
      });
      if (!ack.ok) {
        console.warn("Mensagem recusada pelo backend", ack);
        return; // mantém o texto para o usuário corrigir
      }
      setText("");
      if (ref.current) resize(ref.current);
      ref.current?.focus();
    } catch (error) {
      console.warn("Envio falhou (offline/timeout)", error);
    } finally {
      setSending(false);
    }
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) {
      return;
    }
    event.preventDefault();
    void send();
  };

  const canSend = connected && text.trim().length > 0 && !sending;

  return (
    <div className="flex shrink-0 items-end gap-2 px-4 pb-4 pt-3">
      <textarea
        ref={ref}
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          resize(event.target);
        }}
        onKeyDown={onKeyDown}
        disabled={!connected}
        maxLength={MAX_LENGTH}
        rows={1}
        aria-label="Mensagem para a Polaris"
        placeholder={connected ? "Digite uma mensagem para a Polaris…" : "Conecte ao backend para enviar…"}
        className="block min-w-0 flex-1 resize-none overflow-y-auto border border-line bg-panel px-3 py-2 text-[0.875rem] text-text outline-none transition-colors placeholder:text-dim focus:border-text/40 disabled:cursor-not-allowed disabled:opacity-50"
      />
      <button
        type="button"
        onClick={() => void send()}
        disabled={!canSend}
        aria-label="Enviar mensagem"
        className="flex h-9 w-9 shrink-0 items-center justify-center border border-line bg-panel text-dim transition-colors hover:border-text/40 hover:text-text disabled:cursor-not-allowed disabled:opacity-40"
      >
        <SendIcon />
      </button>
    </div>
  );
}
