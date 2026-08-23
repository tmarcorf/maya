/**
 * Palco do orb — canvas WebGL dirigido imperativamente.
 *
 * O React só monta o canvas e faz o teardown. Todo o resto (loop de render,
 * áudio, uniforms) vive fora da árvore: nenhum estado de componente muda a
 * 60 fps.
 */

import { useEffect, useRef, useState } from "react";

import { useOrbSettingsStore } from "@/store/useOrbSettingsStore";

import { BridgeAudioSource } from "./bridgeAudio";
import { applyOrbSettings, setOrbVisualizer } from "./engineRegistry";
import { useOrbEngine } from "./useOrbEngine";
import { Visualizer } from "./visualizer";

export function OrbStage() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [audio, setAudio] = useState<BridgeAudioSource | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const stage = canvas?.parentElement;
    if (!canvas || !stage) return;

    const visualizer = new Visualizer(canvas, stage);
    const source = new BridgeAudioSource();

    setOrbVisualizer(visualizer);
    // A store é a verdade corrente: o localStorage pode estar atrasado pelo
    // throttle de gravação, e num remount os ajustes já estão em memória.
    applyOrbSettings(useOrbSettingsStore.getState());
    visualizer.start(source);
    setAudio(source);

    return () => {
      // StrictMode monta duas vezes em dev: o teardown precisa devolver o
      // contexto WebGL, ou a segunda montagem herda um canvas morto.
      setOrbVisualizer(null);
      visualizer.dispose();
      setAudio(null);
    };
  }, []);

  useOrbEngine(audio);

  return <canvas ref={canvasRef} className="block h-full w-full" aria-hidden="true" />;
}
