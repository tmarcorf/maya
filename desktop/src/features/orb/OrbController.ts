/**
 * Orb Three.js vanilla — controller imperativo, zero React no hot path.
 *
 * Referência visual: print do usuário (Imagens/polaris) + vídeo de
 * inspiração — uma esfera escura de vidro envolvida por um ANEL de
 * partículas com gradiente rosa → lavanda → azul. As partículas orbitam
 * calculadas na GPU e aceleram com a energia do estado (nível de áudio
 * da fala quando a Polaris fala).
 *
 * Performance (GPU compartilhada com STT CUDA / Qwen3-TTS):
 * - partículas animadas 100% na GPU (attributes + shader — zero custo
 *   de CPU por frame além de ~8 uniforms);
 * - DPR com cap em 2;
 * - trabalho pulado quando a janela está oculta (`document.hidden` +
 *   `backgroundThrottling` do Electron);
 * - `powerPreference: "low-power"`.
 */

import * as THREE from "three";

import type { VoiceState } from "@/shared/protocol";
import { STATE_META } from "@/shared/stateMeta";

import {
  ORB_CORE_FRAGMENT_SHADER,
  ORB_CORE_VERTEX_SHADER,
  ORB_PARTICLES_FRAGMENT_SHADER,
  ORB_PARTICLES_VERTEX_SHADER,
} from "./shaders";

interface OrbPalette {
  top: THREE.Color; // rosa/lavanda no alto do anel
  bottom: THREE.Color; // azul/violeta embaixo
  energyBase: number; // movimento mínimo do estado
  energyLevelScale: number; // ganho a partir do nível de áudio (fala)
}

/**
 * Color cru a partir de hex sRGB — `setRGB` ignora o color management do
 * three (sem conversão sRGB↔linear): o shader escreve os componentes
 * exatamente como foram definidos e o canvas os exibe 1:1.
 */
function rawHex(color: string): THREE.Color {
  const value = Number.parseInt(color.slice(1), 16);
  return new THREE.Color().setRGB(
    ((value >> 16) & 0xff) / 255,
    ((value >> 8) & 0xff) / 255,
    (value & 0xff) / 255,
  );
}

/**
 * Paleta por estado — o topo vem de `STATE_META` (single source com o
 * readout do painel), o fundo complementa dentro da família do print.
 * A energia por estado: idle quieto · listening atento · você fala com
 * o nível do mic · thinking agitado · speaking com o nível do TTS.
 */
const PALETTES: Record<VoiceState, OrbPalette> = {
  idle: {
    top: rawHex(STATE_META.idle.color),
    bottom: rawHex("#5a6fb8"),
    energyBase: 0.07,
    energyLevelScale: 0,
  },
  listening: {
    top: rawHex(STATE_META.listening.color),
    bottom: rawHex("#4f7ec0"),
    energyBase: 0.2,
    energyLevelScale: 0,
  },
  user_speaking: {
    top: rawHex(STATE_META.user_speaking.color),
    bottom: rawHex("#7a6fc0"),
    energyBase: 0.15,
    energyLevelScale: 0.8, // nível do mic
  },
  thinking: {
    top: rawHex(STATE_META.thinking.color),
    bottom: rawHex("#6a5ab0"),
    energyBase: 0.42,
    energyLevelScale: 0,
  },
  speaking: {
    top: rawHex(STATE_META.speaking.color),
    bottom: rawHex("#8a7ad0"),
    energyBase: 0.28,
    energyLevelScale: 0.7, // nível do TTS
  },
};

// Geometria do orb (em unidades de mundo; câmera em z=4.6, fov 45).
const CORE_RADIUS = 0.6;
const RING_MAJOR_RADIUS = 1.25;
const RING_TUBE = 0.22; // dispersão perpendicular ao círculo do anel
const RING_TILT = 0.22; // rad, em torno de X — a elipse do print
const PARTICLE_COUNT = 1200;

const ENERGY_SMOOTH_RATE = 8; // 1/s — suavização exponencial da energia
const COLOR_LERP_RATE = 4; // 1/s — transição entre paletas

export class OrbController {
  private canvas: HTMLCanvasElement | null = null;
  private renderer: THREE.WebGLRenderer | null = null;
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(45, 1, 0.1, 20);
  private readonly group = new THREE.Group();
  private coreMaterial: THREE.ShaderMaterial | null = null;
  private particlesMaterial: THREE.ShaderMaterial | null = null;
  private readonly clock = new THREE.Clock();
  private flowTime = 0;
  private rafId: number | null = null;
  private resizeObserver: ResizeObserver | null = null;
  private disposed = false;
  private state: VoiceState = "idle";
  private readonly levels = { input: 0, output: 0 };
  private smoothEnergy = PALETTES.idle.energyBase;
  private readonly currentTop = PALETTES.idle.top.clone();
  private readonly currentBottom = PALETTES.idle.bottom.clone();

  init(canvas: HTMLCanvasElement): void {
    this.canvas = canvas;
    const renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
      powerPreference: "low-power",
    });
    renderer.setClearColor(0x000000, 0);
    this.renderer = renderer;

    // Núcleo: esfera escura de vidro com rim tingido pelo gradiente.
    const coreGeometry = new THREE.IcosahedronGeometry(CORE_RADIUS, 5);
    const coreUniforms = {
      uTime: { value: 0 },
      uAmplitude: { value: 0.035 },
      uColorTop: { value: new THREE.Vector3() },
      uColorBottom: { value: new THREE.Vector3() },
      uRimPower: { value: 3.4 },
      uEnergy: { value: 0.07 },
    };
    this.coreMaterial = new THREE.ShaderMaterial({
      vertexShader: ORB_CORE_VERTEX_SHADER,
      fragmentShader: ORB_CORE_FRAGMENT_SHADER,
      uniforms: coreUniforms,
    });
    const core = new THREE.Mesh(coreGeometry, this.coreMaterial);
    this.group.add(core);

    // Anel de partículas: órbita na GPU a partir dos attributes.
    const particlesUniforms = {
      uTime: { value: 0 },
      uEnergy: { value: 0.07 },
      uColorTop: { value: new THREE.Vector3() },
      uColorBottom: { value: new THREE.Vector3() },
    };
    this.particlesMaterial = new THREE.ShaderMaterial({
      vertexShader: ORB_PARTICLES_VERTEX_SHADER,
      fragmentShader: ORB_PARTICLES_FRAGMENT_SHADER,
      uniforms: particlesUniforms,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const particlesGeometry = buildRingGeometry(PARTICLE_COUNT);
    const particles = new THREE.Points(particlesGeometry, this.particlesMaterial);
    this.group.add(particles);

    this.group.rotation.x = -RING_TILT;
    this.scene.add(this.group);
    this.camera.position.z = 4.2;

    this.resize();
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(canvas.parentElement ?? canvas);

    document.addEventListener("visibilitychange", this.onVisibilityChange);
    this.startLoop();
  }

  setState(state: VoiceState): void {
    if (state === this.state) return;
    this.state = state;
  }

  setLevels(input: number, output: number): void {
    this.levels.input = input;
    this.levels.output = output;
  }

  dispose(): void {
    this.disposed = true;
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
    document.removeEventListener("visibilitychange", this.onVisibilityChange);
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
    this.scene.traverse((object) => {
      if (object instanceof THREE.Mesh || object instanceof THREE.Points) {
        object.geometry.dispose();
        (object.material as THREE.Material | undefined)?.dispose();
      }
    });
    this.renderer?.dispose();
    this.renderer = null;
    this.canvas = null;
  }

  private readonly onVisibilityChange = (): void => {
    if (document.hidden) return;
    this.startLoop();
  };

  private startLoop(): void {
    if (this.rafId !== null || this.disposed) return;
    const tick = (): void => {
      this.rafId = requestAnimationFrame(tick);
      this.update();
    };
    this.rafId = requestAnimationFrame(tick);
  }

  private resize(): void {
    const renderer = this.renderer;
    const canvas = this.canvas;
    if (!renderer || !canvas) return;
    const parent = canvas.parentElement;
    const width = parent ? parent.clientWidth : canvas.clientWidth;
    const height = parent ? parent.clientHeight : canvas.clientHeight;
    if (width <= 0 || height <= 0) return;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(width, height, false); // CSS controla o layout
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
  }

  private update(): void {
    if (document.hidden || this.disposed) return;
    const core = this.coreMaterial;
    const particles = this.particlesMaterial;
    if (!core || !particles) return;

    const dt = Math.min(this.clock.getDelta(), 0.1);
    const elapsed = this.clock.elapsedTime;
    const palette = PALETTES[this.state];

    // Energia = base do estado + nível de áudio (fala/mic), suavizada.
    const rawLevel =
      this.state === "user_speaking"
        ? this.levels.input
        : this.state === "speaking"
          ? this.levels.output
          : 0;
    const target =
      palette.energyBase + rawLevel * palette.energyLevelScale;
    this.smoothEnergy +=
      (target - this.smoothEnergy) * (1 - Math.exp(-dt * ENERGY_SMOOTH_RATE));
    // Respiração sutil no idle.
    const breathe =
      this.state === "idle" ? Math.sin(elapsed * Math.PI) * 0.03 : 0;
    const energy = Math.max(0, Math.min(1, this.smoothEnergy + breathe));

    // Transição suave de cores entre paletas (uniform Vector3 = cru,
    // sem conversão de color space).
    const k = 1 - Math.exp(-dt * COLOR_LERP_RATE);
    this.currentTop.lerp(palette.top, k);
    this.currentBottom.lerp(palette.bottom, k);
    syncColor(core.uniforms, this.currentTop, this.currentBottom);
    syncColor(particles.uniforms, this.currentTop, this.currentBottom);

    // Tempo integrado (trocar de paleta não "pula" a animação).
    this.flowTime += dt;
    core.uniforms.uTime.value = this.flowTime;
    particles.uniforms.uTime.value = this.flowTime;
    core.uniforms.uEnergy.value = energy;
    particles.uniforms.uEnergy.value = energy;

    // Rotação lenta + balanço — a vida sem fala.
    this.group.rotation.y += dt * (0.12 + energy * 0.35);
    this.group.rotation.x = -RING_TILT + Math.sin(elapsed * 0.25) * 0.04;

    this.renderer?.render(this.scene, this.camera);
  }
}

function syncColor(
  uniforms: Record<string, THREE.IUniform>,
  top: THREE.Color,
  bottom: THREE.Color,
): void {
  const topUniform = uniforms.uColorTop.value as THREE.Vector3;
  const bottomUniform = uniforms.uColorBottom.value as THREE.Vector3;
  topUniform.set(top.r, top.g, top.b);
  bottomUniform.set(bottom.r, bottom.g, bottom.b);
}

/**
 * Distribui as partículas num toro (anel, no frame LOCAL do grupo — a
 * inclinação fica no `group.rotation.x`) e pré-computa os attributes da
 * órbita: ponto unitário no anel + tangente (⊥), fase, velocidade, raio
 * (com dispersão do tubo) e tamanho.
 */
function buildRingGeometry(count: number): THREE.BufferGeometry {
  const p0 = new Float32Array(count * 3);
  const axis = new Float32Array(count * 3);
  const phase = new Float32Array(count);
  const speed = new Float32Array(count);
  const radius = new Float32Array(count);
  const size = new Float32Array(count);

  for (let i = 0; i < count; i++) {
    const phi = Math.random() * Math.PI * 2;
    // Dispersão gaussiana grosseira (soma de uniformes) ⊥ ao círculo.
    const scatter = (Math.random() + Math.random() - 1) * RING_TUBE;
    const wobbleY = (Math.random() + Math.random() - 1) * RING_TUBE * 0.55;
    const dirX = Math.cos(phi);
    const dirZ = Math.sin(phi);

    // Ponto no círculo do anel + dispersão; normaliza para unitário.
    const x = dirX + dirX * scatter;
    const y = wobbleY;
    const z = dirZ + dirZ * scatter;
    const len = Math.hypot(x, y, z) || 1;

    p0[i * 3] = x / len;
    p0[i * 3 + 1] = y / len;
    p0[i * 3 + 2] = z / len;
    // Tangente do círculo (⊥ ao raio).
    axis[i * 3] = -dirZ;
    axis[i * 3 + 1] = 0;
    axis[i * 3 + 2] = dirX;
    phase[i] = Math.random() * Math.PI * 2;
    speed[i] = 0.6 + Math.random();
    radius[i] = RING_MAJOR_RADIUS * (0.96 + Math.random() * 0.08);
    size[i] = 0.5 + Math.random() * 0.7;
  }

  const geometry = new THREE.BufferGeometry();
  // `position` não é lido pelo shader (a órbita vem de aP0/aAxis), mas o
  // three precisa dele para o bounding volume e o draw count.
  geometry.setAttribute("position", new THREE.BufferAttribute(p0, 3));
  geometry.setAttribute("aP0", new THREE.BufferAttribute(p0, 3));
  geometry.setAttribute("aAxis", new THREE.BufferAttribute(axis, 3));
  geometry.setAttribute("aPhase", new THREE.BufferAttribute(phase, 1));
  geometry.setAttribute("aSpeed", new THREE.BufferAttribute(speed, 1));
  geometry.setAttribute("aRadius", new THREE.BufferAttribute(radius, 1));
  geometry.setAttribute("aSize", new THREE.BufferAttribute(size, 1));
  return geometry;
}
