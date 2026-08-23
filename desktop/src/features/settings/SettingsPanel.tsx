/**
 * Gaveta de ajustes — visual do orb + wake word.
 *
 * Os sliders escrevem na store, que empurra os valores direto para o motor;
 * arrastar não re-renderiza nada além do próprio controle. O toggle de wake
 * word é o mesmo componente de sempre, com a lógica de ack intacta.
 */

import { useEffect } from "react";

import { ORB_SLIDERS } from "@/features/orb/orbSettings";
import type { SliderSpec } from "@/features/orb/orbSettings";
import { PALETTES, PALETTE_KEYS } from "@/features/orb/visualizer";
import type { PaletteKey } from "@/features/orb/visualizer";
import { WakeToggle } from "@/features/wake-word/WakeToggle";
import { useOrbSettingsStore } from "@/store/useOrbSettingsStore";

function CloseIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-3.5 w-3.5"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
  );
}

function SliderRow({ spec }: { spec: SliderSpec }) {
  const value = useOrbSettingsStore((s) => s[spec.key]);
  const setValue = useOrbSettingsStore((s) => s.setValue);

  return (
    <label className="flex flex-col gap-1.5">
      <span className="flex items-baseline justify-between gap-2">
        <span className="eyebrow text-text">{spec.label}</span>
        <span className="font-mono text-[0.7rem] text-dim">{value.toFixed(2)}</span>
      </span>
      <input
        type="range"
        min={spec.min}
        max={spec.max}
        step={spec.step}
        value={value}
        onChange={(event) => setValue(spec.key, Number(event.target.value))}
        className="orb-slider"
      />
      <span className="text-[0.7rem] text-dim">{spec.hint}</span>
    </label>
  );
}

function PaletteSwatch({ palette }: { palette: PaletteKey }) {
  const active = useOrbSettingsStore((s) => s.palette === palette);
  const setPalette = useOrbSettingsStore((s) => s.setPalette);
  const { label, top, mid, bottom } = PALETTES[palette];

  const gradient = [top, mid, bottom]
    .map((color) => `#${color.toString(16).padStart(6, "0")}`)
    .join(", ");

  return (
    <button
      type="button"
      onClick={() => setPalette(palette)}
      aria-pressed={active}
      title={label}
      className={
        active
          ? "flex flex-col gap-1.5 border border-text/50 bg-panel p-1.5"
          : "flex flex-col gap-1.5 border border-line bg-panel p-1.5 hover:border-text/30"
      }
    >
      <span
        className="h-6 w-full"
        style={{ background: `linear-gradient(180deg, ${gradient})` }}
        aria-hidden="true"
      />
      <span className={active ? "eyebrow text-text" : "eyebrow text-dim"}>{label}</span>
    </button>
  );
}

export function SettingsPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/50"
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Ajustes"
        className="fixed right-0 top-0 z-50 flex h-full w-80 max-w-[90vw] flex-col border-l border-line bg-ink shadow-2xl"
      >
        <header className="flex shrink-0 items-center justify-between border-b border-line px-4 py-3">
          <span className="eyebrow text-text">Ajustes</span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar ajustes"
            className="border border-line p-1.5 text-dim transition-colors hover:border-text/40 hover:text-text"
          >
            <CloseIcon />
          </button>
        </header>

        <div className="chat-scroll flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-4 py-4">
          <section className="flex flex-col gap-2">
            <span className="eyebrow text-dim">Voz</span>
            <WakeToggle />
          </section>

          <section className="flex flex-col gap-2">
            <span className="eyebrow text-dim">Paleta</span>
            <div className="grid grid-cols-2 gap-2">
              {PALETTE_KEYS.map((key) => (
                <PaletteSwatch key={key} palette={key} />
              ))}
            </div>
          </section>

          <section className="flex flex-col gap-4">
            <span className="eyebrow text-dim">Visual do orb</span>
            {ORB_SLIDERS.map((spec) => (
              <SliderRow key={spec.key} spec={spec} />
            ))}
          </section>

          <button
            type="button"
            onClick={() => useOrbSettingsStore.getState().reset()}
            className="eyebrow border border-line px-3 py-2 text-dim transition-colors hover:border-text/40 hover:text-text"
          >
            Restaurar padrões
          </button>
        </div>
      </aside>
    </>
  );
}

export function SettingsButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Abrir ajustes"
      className="border border-line bg-panel p-1.5 text-dim transition-colors hover:border-text/40 hover:text-text"
    >
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
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z" />
      </svg>
    </button>
  );
}
