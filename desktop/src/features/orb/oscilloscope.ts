/**
 * Osciloscópio — o traço brilhante sob o orb, no estilo das camadas do orb.
 *
 * O React só monta o canvas; todo o resto vive fora da árvore, como no
 * `Visualizer`. O traço é dirigido pelo espectro do lado ativo da bridge
 * (quando a Maya fala, o lado ativo é o output — o espectro do TTS), e
 * só desenha no estado `speaking`: fora dele, decai para a linha plana em
 * vez de congelar.
 *
 * O renderer usa `alpha: true` e não tem `scene.background`: o gradiente da
 * paleta do palco aparece através do canvas.
 */

import * as THREE from "three";

import type { AudioLevels } from "@/store/useLevelStore";

/** Pontos do traço. */
const TRACE_POINTS = 192;

/** Bin mais alto considerado na síntese (o espectro da bridge costuma ter 48). */
const MAX_BINS = 48;

const TWO_PI = Math.PI * 2;

/**
 * Sintetiza a forma de onda do traço a partir do espectro de magnitude.
 *
 * Cada bin vira um harmônico com uma fase própria (que deriva lentamente),
 * então a silhueta acompanha de verdade o timbre e o volume do áudio — o
 * mesmo princípio do orb, que também é dirigido pelo espectro.
 *
 * Função pura, exportada para os testes.
 */
export function traceFromSpectrum(
  spectrum: Uint8Array,
  phases: Float32Array,
  level: number,
  points: number,
): Float32Array {
  const trace = new Float32Array(points);
  const bins = Math.min(spectrum.length, phases.length, MAX_BINS);
  if (level <= 0 || bins === 0) return trace;

  // Normaliza pela energia real (Σ a²): a amplitude do traço não depende de
  // quantos bins estão ativos — só da forma do espectro e do volume.
  let energy = 0;
  for (let b = 0; b < bins; b++) {
    const amp = spectrum[b] / 255;
    energy += amp * amp;
  }
  if (energy === 0) return trace;
  const gain = (Math.min(level * 1.25, 1.1) * 1.35) / Math.sqrt(energy);

  for (let i = 0; i < points; i++) {
    const u = i / (points - 1);
    let y = 0;
    for (let b = 0; b < bins; b++) {
      const amp = spectrum[b] / 255;
      if (amp <= 0) continue;
      y += amp * Math.sin(TWO_PI * (b + 1) * u + phases[b]);
    }
    trace[i] = y * gain;
  }
  return trace;
}

/** Fase pseudo-aleatória por bin, determinística — cada bin deriva em ritmo próprio. */
function phaseStep(seed: number): number {
  const hash = Math.sin(seed * 127.1 + 311.7) * 43758.5453;
  return 0.25 + (hash - Math.floor(hash)) * 0.45;
}

interface TraceLayer {
  line: THREE.Line;
  material: THREE.ShaderMaterial;
  positions: Float32Array;
  /** Dilatação vertical do traço — o halo é uma cópia mais alta, por baixo. */
  dilation: number;
}

export class Oscilloscope {
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene: THREE.Scene;
  private readonly camera: THREE.OrthographicCamera;
  private readonly layers: [TraceLayer, TraceLayer];
  private readonly resizeObserver: ResizeObserver;

  private readonly spectrum = new Uint8Array(MAX_BINS);
  private readonly phases = new Float32Array(MAX_BINS);
  private level = 0;
  private targetLevel = 0;
  private active = false;
  private running = false;

  /** Mesmo loop do orb: setInterval a 60 Hz, não rAF (ver Visualizer). */
  private static readonly RENDER_INTERVAL_MS = 1000 / 60;
  private timerId = 0;

  constructor(canvas: HTMLCanvasElement) {
    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
      powerPreference: "high-performance",
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));

    this.scene = new THREE.Scene();
    this.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, -1, 1);

    // Dois traços sobrepostos, como as camadas do orb: o halo (cópia mais
    // alta, translúcida) e o núcleo (fino, quente). AdditiveBlending sobre o
    // fundo escuro dá o neon — lineWidth do WebGL é capado em 1px, então o
    // halo não vem de linhas mais grossas.
    this.layers = [
      this.buildLayer(1.12, 0.16, 0.0),
      this.buildLayer(1.0, 0.95, 0.45),
    ];
    for (const layer of this.layers) this.scene.add(layer.line);

    for (let b = 0; b < MAX_BINS; b++) this.phases[b] = phaseStep(b + 1);

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(canvas);
    this.resize();
  }

  private buildLayer(dilation: number, opacity: number, whiteMix: number): TraceLayer {
    const positions = new Float32Array(TRACE_POINTS * 3);
    const fade = new Float32Array(TRACE_POINTS);
    for (let i = 0; i < TRACE_POINTS; i++) {
      const u = i / (TRACE_POINTS - 1);
      // Esmaece só nas pontas — o arco não "corta" nas bordas do canvas.
      fade[i] = Math.min(1, Math.min(u, 1 - u) * 6);
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute("aFade", new THREE.BufferAttribute(fade, 1));

    const material = new THREE.ShaderMaterial({
      uniforms: {
        uColor: { value: new THREE.Color(0x2ec5ff) },
        uOpacity: { value: opacity },
        uWhiteMix: { value: whiteMix },
      },
      vertexShader: /* glsl */ `
        attribute float aFade;
        varying float vFade;
        void main() {
          vFade = aFade;
          gl_Position = vec4(position.xy, 0.0, 1.0);
        }
      `,
      fragmentShader: /* glsl */ `
        uniform vec3 uColor;
        uniform float uOpacity;
        uniform float uWhiteMix;
        varying float vFade;
        void main() {
          // Núcleo quente: mistura para o branco como os spikes do orb.
          vec3 color = mix(uColor, vec3(1.0), uWhiteMix);
          gl_FragColor = vec4(color, clamp(vFade * uOpacity, 0.0, 1.0));
        }
      `,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });

    const line = new THREE.Line(geometry, material);
    line.frustumCulled = false;
    return { line, material, positions, dilation };
  }

  /** Recebe o último `audio_level`. Chamado pelo `useOscilloscopeEngine`. */
  ingest(levels: AudioLevels): void {
    const raw = levels.spectrum ?? [];
    if (raw.length > 0) {
      const bins = Math.min(raw.length, MAX_BINS);
      for (let b = 0; b < bins; b++) this.spectrum[b] = raw[b];
      for (let b = bins; b < MAX_BINS; b++) this.spectrum[b] = 0;
    } else {
      // Bridge sem FFT: um espectro inclinado, escalado pelo volume, mantém a
      // silhueta viva (mesmo padrão do adaptador do orb).
      const rms = levels.level ?? Math.max(levels.input, levels.output);
      for (let b = 0; b < MAX_BINS; b++) {
        const u = b / MAX_BINS;
        this.spectrum[b] = Math.min(255, Math.round(Math.pow(1 - u, 1.8) * rms * 255));
      }
    }
    this.targetLevel = levels.level ?? Math.max(levels.input, levels.output);

    // Histerese contra chacoalho de nível: só acorda o loop com sinal real.
    if (!this.running && this.targetLevel > 0.02) this.start();
  }

  /** Só desenha quando a Maya está falando; fora disso decai para plano. */
  setActive(active: boolean): void {
    this.active = active;
    if (active) this.start();
  }

  /** A cor do sul do orb (palette.bottom), trocada quando a paleta muda. */
  setColor(hex: number): void {
    for (const layer of this.layers) {
      layer.material.uniforms.uColor.value.set(hex);
    }
  }

  private resize(): void {
    const canvas = this.renderer.domElement;
    const width = canvas.clientWidth || canvas.parentElement?.clientWidth || 1;
    const height = canvas.clientHeight || canvas.parentElement?.clientHeight || 1;
    this.renderer.setSize(width, height, false);
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    // setInterval e não rAF — o display de 180 Hz faria o compositor rodar
    // um BeginFrame por vblank (ver Visualizer.RENDER_INTERVAL_MS).
    this.timerId = window.setInterval(() => this.frame(), Oscilloscope.RENDER_INTERVAL_MS);
  }

  stop(): void {
    if (!this.running) return;
    this.running = false;
    clearInterval(this.timerId);
    this.timerId = 0;
  }

  private frame(): void {
    const dt = 1 / 60;

    // Fases derivam lentamente: o traço nunca congela nem repete a silhueta.
    for (let b = 0; b < MAX_BINS; b++) {
      this.phases[b] = (this.phases[b] + dt * phaseStep(b + 2)) % TWO_PI;
    }

    // Ataque rápido, soltura mais lenta — acompanha a fala sem tremer.
    const target = this.active ? this.targetLevel : 0;
    const rate = target > this.level ? 0.25 : 0.09;
    this.level += (target - this.level) * rate;

    // Inativo e já na linha plana: congela o loop — o último frame desenhou o
    // traço estático, e retomar deixa o frame seguinte idêntico. Acorda via
    // `setActive(true)` ou `ingest` com sinal acima da histerese.
    if (!this.active && this.level < 0.01) {
      this.stop();
      return;
    }

    const trace = traceFromSpectrum(this.spectrum, this.phases, this.level, TRACE_POINTS);
    for (const layer of this.layers) {
      const positions = layer.positions;
      for (let i = 0; i < TRACE_POINTS; i++) {
        positions[i * 3] = (i / (TRACE_POINTS - 1)) * 2 - 1;
        // Leve deslocamento para baixo: o traço fica sob o orb, não no meio.
        positions[i * 3 + 1] = trace[i] * 1.15 * layer.dilation - 0.12;
        positions[i * 3 + 2] = 0;
      }
      layer.line.geometry.attributes.position.needsUpdate = true;
    }

    this.renderer.render(this.scene, this.camera);
  }

  dispose(): void {
    this.stop();
    this.resizeObserver.disconnect();
    for (const layer of this.layers) {
      layer.line.geometry.dispose();
      layer.material.dispose();
    }
    this.renderer.dispose();
  }
}
