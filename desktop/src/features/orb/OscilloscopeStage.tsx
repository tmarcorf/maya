/**
 * Osciloscópio do palco — o traço brilhante sob o orb.
 *
 * Como o `OrbStage`: o React só monta o canvas e o teardown; o loop vive
 * fora da árvore. A visibilidade vem do estado da bridge (`speaking`), com
 * fade CSS — o WebGL continua rodando por baixo e decai para a linha plana.
 */

import { useEffect, useRef, useState } from "react";

import { useBridgeStore } from "@/store/useBridgeStore";

import { Oscilloscope } from "./oscilloscope";
import { useOscilloscopeEngine } from "./useOscilloscopeEngine";

export function OscilloscopeStage() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [oscilloscope, setOscilloscope] = useState<Oscilloscope | null>(null);
  const speaking = useBridgeStore((s) => s.voice === "speaking");

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const scope = new Oscilloscope(canvas);
    scope.start();
    setOscilloscope(scope);

    return () => {
      // StrictMode monta duas vezes em dev: o teardown precisa devolver o
      // contexto WebGL, ou a segunda montagem herda um canvas morto.
      scope.dispose();
      setOscilloscope(null);
    };
  }, []);

  useOscilloscopeEngine(oscilloscope);

  return (
    <div
      className={speaking ? "oscilloscope-wrap" : "oscilloscope-wrap oscilloscope-hidden"}
      aria-hidden="true"
    >
      <canvas ref={canvasRef} className="block h-full w-full" />
    </div>
  );
}
