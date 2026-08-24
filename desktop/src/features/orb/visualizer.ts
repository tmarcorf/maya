import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { ShaderPass } from "three/addons/postprocessing/ShaderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";

import { Orb } from "./orb";
import { GradeShader } from "./shaders/grade";
import type { AudioFrame, OrbPalette, OrbSettings } from "./types";

export const PALETTES = {
  ember: {
    label: "Ember / Ice",
    top: 0xff3d10,
    upper: 0xff6a4a,
    mid: 0x9d5ad8,
    lower: 0x4f7bf0,
    bottom: 0x2ec5ff,
    flareTop: 0xff7a3c,
    flareBottom: 0x59d8ff,
    background: ["#132133", "#04060c"],
  },
  toxic: {
    label: "Toxic",
    top: 0xd8ff3a,
    upper: 0x6cf07a,
    mid: 0x22c8a8,
    lower: 0x1f8fd0,
    bottom: 0x6a3cff,
    flareTop: 0xc4ff5a,
    flareBottom: 0x8a5cff,
    background: ["#0a1a1c", "#03070a"],
  },
  magma: {
    label: "Magma",
    top: 0xfff1b0,
    upper: 0xffa22a,
    mid: 0xff4d16,
    lower: 0xc01038,
    bottom: 0x5a0a4a,
    flareTop: 0xffd08a,
    flareBottom: 0xff5a2a,
    background: ["#1c0f0a", "#080304"],
  },
  frost: {
    label: "Frost",
    top: 0xeafcff,
    upper: 0x7fe4ff,
    mid: 0x3f9bf0,
    lower: 0x3350d8,
    bottom: 0x6a2ce0,
    flareTop: 0xd6f6ff,
    flareBottom: 0x8a6cff,
    background: ["#0a1424", "#03050b"],
  },
} as const satisfies Record<string, OrbPalette>;

export type PaletteKey = keyof typeof PALETTES;

export const PALETTE_KEYS = Object.keys(PALETTES) as PaletteKey[];

export function isPaletteKey(value: unknown): value is PaletteKey {
  return typeof value === "string" && value in PALETTES;
}

/** Fonte de áudio que o loop consome — implementada por `BridgeAudioSource`. */
export interface AudioSource {
  sensitivity: number;
  read(dt: number): AudioFrame;
}

const DEFAULT_CAMERA = new THREE.Vector3(0, -0.12, 4.1);

export class Visualizer {
  readonly settings: OrbSettings & { palette: PaletteKey } = {
    turbulence: 1,
    detail: 0.5,
    speed: 1,
    glow: 1,
    bloom: 0.9,
    sensitivity: 1,
    resolution: 1.5,
    palette: "ember",
  };

  readonly orb: Orb;
  fps = 0;
  onFrame?: (audio: AudioFrame, visualizer: Visualizer) => void;

  private readonly canvas: HTMLCanvasElement;
  private readonly container: HTMLElement;
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene: THREE.Scene;
  private readonly camera: THREE.PerspectiveCamera;
  private readonly controls: OrbitControls;
  private readonly composer: EffectComposer;
  private readonly bloom: UnrealBloomPass;
  private readonly grade: ShaderPass;
  private readonly timer: THREE.Timer;
  private readonly resizeObserver: ResizeObserver;

  private audio: AudioSource | null = null;
  private frames = 0;
  private fpsClock = 0;
  private pendingCapture: ((blob: Blob | null) => void) | null = null;

  /**
   * O loop é um setInterval de 60 Hz — de propósito, não rAF. O display
   * entrega 180 Hz e o rAF registrado faz o compositor do Chromium rodar um
   * BeginFrame a cada vblank: ~0.74 ms de CPU nativa na thread principal por
   * rAF, mesmo quando o código não renderiza (medido: ~133% de 1 core com o
   * render já capado a 60 fps). Sem rAF registrado, o Chromium só roda
   * BeginFrame quando o canvas fica dirty — 1× por render, não 3× por vblank.
   * O dt do Timer mede o tempo real, então o jitter do setInterval não
   * acelera nem congela nada: a animação fica contínua a 60 Hz por ~1/7 do
   * custo original (180 rAF/s) — e os envelopes do áudio voltam à cadência
   * de 60 Hz do design, que rodava 3× mais rápido por conta do display.
   */
  private static readonly RENDER_INTERVAL_MS = 1000 / 60;
  private timerId = 0;

  /**
   * Cap do pixel ratio. 1.5 é o equilíbrio: 4×→2.25× pixels e ~44% menos
   * fragmento em todos os passes do composer, imperceptível com o bloom.
   */
  private _dprCap = 1.5;

  /** Cap atual — getter público para o `applyOrbSettings` deduplicar. */
  get dprCap(): number {
    return this._dprCap;
  }

  constructor(canvas: HTMLCanvasElement, container: HTMLElement) {
    this.canvas = canvas;
    this.container = container;

    this.renderer = new THREE.WebGLRenderer({
      canvas,
      // MSAA é desperdício: o bloom do composer já borra o buffer inteiro.
      antialias: false,
      powerPreference: "high-performance",
      stencil: false,
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, this.dprCap));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.15;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
    this.camera.position.copy(DEFAULT_CAMERA);

    this.controls = new OrbitControls(this.camera, canvas);
    // Looking slightly below centre lifts the orb clear of the panel.
    this.controls.target.set(0, DEFAULT_CAMERA.y, 0);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.06;
    this.controls.enablePan = false;
    this.controls.rotateSpeed = 0.45;
    this.controls.zoomSpeed = 0.6;
    this.controls.minDistance = 2.2;
    this.controls.maxDistance = 7;

    this.orb = new Orb();
    this.scene.add(this.orb.group);

    const size = new THREE.Vector2();
    this.renderer.getSize(size);
    this.composer = new EffectComposer(this.renderer);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    this.bloom = new UnrealBloomPass(size, 0.9, 0.62, 0.4);
    this.composer.addPass(this.bloom);
    this.grade = new ShaderPass(GradeShader);
    this.composer.addPass(this.grade);
    this.composer.addPass(new OutputPass());
    // O composer captura o ratio na construção; sincronizar explicitamente
    // para os targets nascerem com o cap (1.5), não com o DPR do display.
    this.composer.setPixelRatio(this.renderer.getPixelRatio());

    this.applyPalette("ember");

    this.timer = new THREE.Timer();

    // O palco é um painel flex: ele muda de tamanho sem a janela mudar (abrir
    // a gaveta de ajustes, arrastar o divisor). Um ResizeObserver cobre os
    // dois casos; um listener de `window.resize` só cobriria um.
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.resize();
  }

  private setBackground([inner, outer]: readonly [string, string]): void {
    const size = 512;
    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const gradient = ctx.createRadialGradient(
      size / 2,
      size * 0.46,
      0,
      size / 2,
      size / 2,
      size * 0.72,
    );
    gradient.addColorStop(0, inner);
    gradient.addColorStop(1, outer);
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, size, size);

    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;

    if (this.scene.background instanceof THREE.Texture) this.scene.background.dispose();
    this.scene.background = texture;
  }

  applyPalette(key: PaletteKey): void {
    const palette = PALETTES[key] ?? PALETTES.ember;
    this.settings.palette = key;
    this.orb.setPalette(palette);
    this.setBackground(palette.background);
  }

  resetCamera(): void {
    this.camera.position.copy(DEFAULT_CAMERA);
    this.controls.target.set(0, DEFAULT_CAMERA.y, 0);
    this.controls.update();
  }

  resize(): void {
    const width = this.container.clientWidth || window.innerWidth;
    const height = this.container.clientHeight || window.innerHeight;
    if (width === 0 || height === 0) return;

    // Janela arrastada para outro display: reaproxima o cap na hora.
    const ratio = Math.min(window.devicePixelRatio, this.dprCap);
    if (this.renderer.getPixelRatio() !== ratio) {
      this.renderer.setPixelRatio(ratio);
      this.composer.setPixelRatio(ratio);
    }

    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();

    this.renderer.setSize(width, height, false);
    this.composer.setSize(width, height);
  }

  /** Ajusta o cap do pixel ratio (slider "Resolução" dos ajustes). */
  setResolution(cap: number): void {
    this._dprCap = Math.min(2, Math.max(1, cap));
    this.resize();
  }

  /** Resolves with a PNG Blob captured from the next rendered frame. */
  capture(): Promise<Blob | null> {
    return new Promise((resolve) => {
      this.pendingCapture = resolve;
    });
  }

  start(audio: AudioSource): void {
    this.audio = audio;
    if (this.timerId) return; // idempotente (StrictMode monta/desmonta duas vezes)
    // setInterval e não rAF — ver RENDER_INTERVAL_MS.
    this.timerId = window.setInterval(() => this.frame(), Visualizer.RENDER_INTERVAL_MS);
  }

  stop(): void {
    clearInterval(this.timerId);
    this.timerId = 0;
  }

  private frame(): void {
    if (!this.audio) return;

    this.timer.update();
    const dt = Math.min(this.timer.getDelta(), 1 / 20);

    this.audio.sensitivity = this.settings.sensitivity;
    const audio = this.audio.read(dt);

    this.orb.update(audio, dt, this.settings);
    this.controls.update();

    // Bloom breathes with the mix; the beat impulse gives it a visible kick.
    const reactive = 0.72 + audio.level * 0.55 + audio.beat * 0.45;
    this.bloom.strength = this.settings.bloom * reactive * this.settings.glow;
    this.bloom.radius = 0.55 + audio.bass * 0.22;

    this.grade.uniforms.uTime.value = this.orb.uniforms.uTime.value;
    this.grade.uniforms.uLevel.value = audio.level;

    this.composer.render();

    if (this.pendingCapture) {
      const resolve = this.pendingCapture;
      this.pendingCapture = null;
      // toBlob snapshots the bitmap synchronously, so call it before yielding --
      // the drawing buffer is cleared once this frame is presented.
      this.canvas.toBlob((blob) => resolve(blob), "image/png");
    }

    this.onFrame?.(audio, this);

    this.frames++;
    this.fpsClock += dt;
    if (this.fpsClock >= 0.5) {
      this.fps = Math.round(this.frames / this.fpsClock);
      this.frames = 0;
      this.fpsClock = 0;
    }
  }

  dispose(): void {
    this.stop();
    this.resizeObserver.disconnect();
    this.controls.dispose();
    this.orb.dispose();
    if (this.scene.background instanceof THREE.Texture) this.scene.background.dispose();
    this.composer.dispose();
    this.renderer.dispose();
  }
}

