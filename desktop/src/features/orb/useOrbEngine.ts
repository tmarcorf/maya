/**
 * Ponte stores → adaptador de áudio do orb, sem re-render por frame.
 *
 * Zustand v5: `subscribe` sem seletor, com guarda manual. O React nunca
 * re-renderiza por causa de áudio a 30 Hz — os valores vão direto para o
 * adaptador, que o loop do `Visualizer` lê uma vez por quadro.
 */

import { useEffect } from "react";

import type { VoiceState } from "@/shared/protocol";
import { useBridgeStore } from "@/store/useBridgeStore";
import { useLevelStore } from "@/store/useLevelStore";

import type { AudioMood, BridgeAudioSource } from "./bridgeAudio";

/**
 * `speaking` é o pulso da fala da Maya — o único estado que pula do
 * áudio real do TTS. `thinking` não tem áudio nenhum fluindo; sem o modo
 * ambiente o orb congelaria exatamente enquanto o Hermes trabalha, que é
 * quando o usuário mais precisa de sinal de que algo está acontecendo.
 */
export function voiceToMood(voice: VoiceState): AudioMood {
  if (voice === "speaking") return "pulse";
  if (voice === "thinking") return "ambient";
  if (voice === "idle") return "rest";
  return "live";
}

export function useOrbEngine(audio: BridgeAudioSource | null): void {
  useEffect(() => {
    if (!audio) return;

    const offLevels = useLevelStore.subscribe((state, prev) => {
      if (state.ts !== prev.ts) audio.ingest(state);
    });
    const offVoice = useBridgeStore.subscribe((state, prev) => {
      if (state.voice !== prev.voice) audio.setMood(voiceToMood(state.voice));
    });

    // Coerência com o estado corrente na montagem.
    audio.ingest(useLevelStore.getState());
    audio.setMood(voiceToMood(useBridgeStore.getState().voice));

    return () => {
      offLevels();
      offVoice();
    };
  }, [audio]);
}
