import { useEffect, useRef, useState, type CSSProperties } from "react";

import { transport } from "@/lib/bridge";
import { PALETTES } from "@/features/orb/visualizer";
import { useBridgeStore } from "@/store/useBridgeStore";
import { useOrbSettingsStore } from "@/store/useOrbSettingsStore";
import type { VoiceState } from "@/shared/protocol";

const WORDS = ["pensando", "analisando", "processando", "verificando", "consultando",
  "calculando", "raciocinando", "refletindo", "buscando", "conferindo"] as const;
const pickWord = () => WORDS[Math.floor(Math.random() * WORDS.length)];
const hex = (value: number) => `#${value.toString(16).padStart(6, "0")}`;

/**
 * Fala a palavra de working com a voz da Maya: o backend sintetiza fora do
 * pipeline (comando `synthesize_word`, WAV base64) e o app toca. Se a
 * resposta já começou a falar quando o áudio chegar, a palavra perde a vez —
 * ela é um aviso de trabalho, não pode atropelar a resposta.
 */
async function speakWord(word: string): Promise<void> {
  const stillThinking = () => useBridgeStore.getState().voice === "thinking";
  if (!stillThinking()) return;
  try {
    const ack = await transport.sendCommand({ cmd: "synthesize_word", text: word });
    if (!ack.ok || !stillThinking()) return;
    const data = ack.data as { wav?: string } | undefined;
    if (!data?.wav) return;
    const audio = new Audio(`data:audio/wav;base64,${data.wav}`);
    audio.volume = 0.9;
    void audio.play().catch(() => {
      /* autoplay/offline: fica só na tela */
    });
  } catch {
    // Bridge offline (mock parado, backend caindo): palavra só na tela.
  }
}

export function WorkingList() {
  const voice = useBridgeStore((s) => s.voice);
  const palette = useOrbSettingsStore((s) => s.palette);
  const [word, setWord] = useState(pickWord);
  // null = acabou de montar: se a Maya já estiver pensando (app reaberto no
  // meio de uma operação), a palavra aparece na tela sem borda de subida —
  // e deve falar mesmo assim.
  const prevVoice = useRef<VoiceState | null>(null);

  useEffect(() => {
    if (voice === "thinking" && prevVoice.current !== "thinking") {
      const next = pickWord();
      setWord(next);
      void speakWord(next);
    }
    prevVoice.current = voice;
  }, [voice]);

  const thinking = voice === "thinking";
  const colors = PALETTES[palette];

  return (
    <span className={thinking ? "working-list" : "working-list working-list-hidden"} aria-hidden="true"
      style={{ "--wl-low": hex(colors.lower), "--wl-mid": hex(colors.mid), "--wl-high": hex(colors.upper) } as CSSProperties}>
      {word}
    </span>
  );
}
