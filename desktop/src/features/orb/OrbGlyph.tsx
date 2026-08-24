/**
 * Glifo do orb — a assinatura da Maya no chat.
 *
 * Retrato 2D do orb 3D: esfera com o gradiente vertical da paleta ativa
 * (top → mid → bottom), um brilho especular no alto e um halo no tom do
 * meio. Substitui o antigo glifo da pirâmide invertida nas respostas da
 * Maya; muda de paleta junto com o orb.
 */

import { PALETTES } from "@/features/orb/visualizer";
import { useOrbSettingsStore } from "@/store/useOrbSettingsStore";

const hex = (value: number) => `#${value.toString(16).padStart(6, "0")}`;

export function OrbGlyph({ className = "h-3.5 w-3.5" }: { className?: string }) {
  const palette = useOrbSettingsStore((s) => s.palette);
  const { top, mid, bottom } = PALETTES[palette];

  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      style={{ filter: `drop-shadow(0 0 3px ${hex(mid)}66)` }}
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={`orb-grad-${palette}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={hex(top)} />
          <stop offset="55%" stopColor={hex(mid)} />
          <stop offset="100%" stopColor={hex(bottom)} />
        </linearGradient>
        <radialGradient id={`orb-sheen-${palette}`} cx="0.35" cy="0.28" r="0.85">
          <stop offset="0%" stopColor="#ffffff" stopOpacity="0.4" />
          <stop offset="45%" stopColor="#ffffff" stopOpacity="0.06" />
          <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx="12" cy="12" r="9.5" fill={`url(#orb-grad-${palette})`} />
      <circle cx="12" cy="12" r="9.5" fill={`url(#orb-sheen-${palette})`} />
      <circle
        cx="12"
        cy="12"
        r="9.5"
        fill="none"
        stroke="#ffffff"
        strokeOpacity="0.14"
        strokeWidth="0.75"
      />
    </svg>
  );
}
