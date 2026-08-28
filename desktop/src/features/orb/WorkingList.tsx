/**
 * Working list — uma palavra de trabalho sob o osciloscópio enquanto a Maya
 * pensa (a resposta ainda não chegou). O gatilho é `voice === "thinking"`
 * (setado no LLMFullResponseStartFrame, quando o LLM começa a gerar); a
 * transição thinking → speaking (TTSStarted/BotStartedSpeaking) é a resposta
 * chegando, e a palavra some sozinha.
 *
 * A palavra troca a cada PENSAMENTO novo, nunca no meio de um; se o
 * componente monta já em "thinking" (mock conecta no meio do ciclo), a
 * palavra inicial vale para o turno corrente. Tudo é ambiental, como o
 * osciloscópio: aria-hidden, pointer-events: none.
 */

import { useEffect, useRef, useState, type CSSProperties } from "react";

import { PALETTES } from "@/features/orb/visualizer";
import { useBridgeStore } from "@/store/useBridgeStore";
import { useOrbSettingsStore } from "@/store/useOrbSettingsStore";

const WORDS = [
  "pensando",
  "analisando",
  "processando",
  "verificando",
  "consultando",
  "calculando",
  "raciocinando",
  "refletindo",
  "buscando",
  "conferindo",
] as const;

function pickWord(): string {
  return WORDS[Math.floor(Math.random() * WORDS.length)];
}

/** Hex de cor do orb → #rrggbb (mesmo helper do OrbGlyph). */
const hex = (value: number) => `#${value.toString(16).padStart(6, "0")}`;

export function WorkingList() {
  const voice = useBridgeStore((s) => s.voice);
  const palette = useOrbSettingsStore((s) => s.palette);
  const [word, setWord] = useState(pickWord);

  // Sorteia só na borda de subida de "thinking"; montar já em "thinking"
  // mantém a palavra inicial (prevVoice já nasce "thinking").
  const prevVoice = useRef(voice);
  useEffect(() => {
    if (voice === "thinking" && prevVoice.current !== "thinking") {
      setWord(pickWord());
    }
    prevVoice.current = voice;
  }, [voice]);

  const thinking = voice === "thinking";
  const colors = PALETTES[palette];

  return (
    <span
      className={thinking ? "working-list" : "working-list working-list-hidden"}
      aria-hidden="true"
      style={
        {
          "--wl-low": hex(colors.lower),
          "--wl-mid": hex(colors.mid),
          "--wl-high": hex(colors.upper),
        } as CSSProperties
      }
    >
      {word}
    </span>
  );
}
