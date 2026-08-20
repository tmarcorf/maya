/**
 * Toggle da wake word — NUNCA otimista.
 *
 * O valor exibido vem do backend (`wake_state`/`state`). O clique envia
 * `set_wake_word_enabled` e o switch fica em "pending" até o ack — se o
 * backend não confirmar (ok=false ou timeout), nada muda.
 */

import { useState } from "react";

import { transport } from "@/lib/bridge";
import { wakeStatusLabel } from "@/shared/stateMeta";
import { useBridgeStore } from "@/store/useBridgeStore";

function MicIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-3.5 w-3.5"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" x2="12" y1="19" y2="22" />
    </svg>
  );
}

export function WakeToggle() {
  const wake = useBridgeStore((s) => s.wake);
  const connected = useBridgeStore((s) => s.connection === "connected");
  const [pending, setPending] = useState(false);

  const toggle = async () => {
    if (pending || !connected) return;
    setPending(true);
    try {
      const ack = await transport.sendCommand({
        cmd: "set_wake_word_enabled",
        enabled: !wake.enabled,
      });
      // O estado só muda quando o backend publicar wake_state; em falha,
      // permanece como está. Nada a fazer com o ack além de logar.
      if (!ack.ok) {
        console.warn("Toggle da wake word recusado pelo backend", ack);
      }
    } catch (error) {
      console.warn("Toggle da wake word falhou (offline/timeout)", error);
    } finally {
      setPending(false);
    }
  };

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={pending || !connected}
      aria-pressed={wake.enabled}
      aria-label={wake.enabled ? "Desativar wake word" : "Ativar wake word"}
      className="group flex items-center gap-2.5 border border-line bg-panel px-3 py-1.5 transition-colors hover:border-text/40 disabled:cursor-not-allowed disabled:opacity-50"
    >
      <MicIcon />
      <span className="eyebrow">Wake word</span>
      <span
        className={
          wake.enabled
            ? "eyebrow text-state-listening"
            : "eyebrow text-dim"
        }
      >
        {pending ? "…" : wake.enabled ? "On" : "Off"}
      </span>
      <span className="eyebrow hidden text-dim group-hover:inline">
        {wake.enabled ? `· ${wakeStatusLabel(wake.state)}` : "· escuta sempre"}
      </span>
    </button>
  );
}
