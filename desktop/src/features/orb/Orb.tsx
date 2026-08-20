/**
 * Orb — canvas isolado com o controller Three.js.
 *
 * O ciclo de vida é todo imperativo (init/dispose no `useEffect`); o React
 * nunca re-renderiza este componente por causa de frames de áudio.
 */

import { useEffect, useRef, useState } from "react";

import { OrbController } from "./OrbController";
import { useOrbEngine } from "./useOrbEngine";

export function Orb() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [controller, setController] = useState<OrbController | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const orb = new OrbController();
    orb.init(canvas);
    setController(orb);
    return () => {
      orb.dispose();
      setController(null);
    };
  }, []);

  useOrbEngine(controller);

  return <canvas ref={canvasRef} className="h-full w-full" aria-hidden="true" />;
}
