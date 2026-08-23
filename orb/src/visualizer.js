import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

import { Orb } from './orb.js';
import { GradeShader } from './shaders/grade.js';

export const PALETTES = {
  ember: {
    label: 'Ember / Ice',
    top: 0xff3d10,
    upper: 0xff6a4a,
    mid: 0x9d5ad8,
    lower: 0x4f7bf0,
    bottom: 0x2ec5ff,
    flareTop: 0xff7a3c,
    flareBottom: 0x59d8ff,
    background: ['#132133', '#04060c'],
  },
  toxic: {
    label: 'Toxic',
    top: 0xd8ff3a,
    upper: 0x6cf07a,
    mid: 0x22c8a8,
    lower: 0x1f8fd0,
    bottom: 0x6a3cff,
    flareTop: 0xc4ff5a,
    flareBottom: 0x8a5cff,
    background: ['#0a1a1c', '#03070a'],
  },
  magma: {
    label: 'Magma',
    top: 0xfff1b0,
    upper: 0xffa22a,
    mid: 0xff4d16,
    lower: 0xc01038,
    bottom: 0x5a0a4a,
    flareTop: 0xffd08a,
    flareBottom: 0xff5a2a,
    background: ['#1c0f0a', '#080304'],
  },
  frost: {
    label: 'Frost',
    top: 0xeafcff,
    upper: 0x7fe4ff,
    mid: 0x3f9bf0,
    lower: 0x3350d8,
    bottom: 0x6a2ce0,
    flareTop: 0xd6f6ff,
    flareBottom: 0x8a6cff,
    background: ['#0a1424', '#03050b'],
  },
};

const DEFAULT_CAMERA = new THREE.Vector3(0, -0.12, 4.1);

export class Visualizer {
  constructor(canvas, container) {
    this.canvas = canvas;
    this.container = container;

    this.settings = {
      turbulence: 1,
      detail: 0.5,
      speed: 1,
      glow: 1,
      bloom: 0.9,
      palette: 'ember',
    };

    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      powerPreference: 'high-performance',
      stencil: false,
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
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

    this._setBackground(PALETTES.ember.background);
    this._buildComposer();
    this.applyPalette('ember');

    this.timer = new THREE.Timer();
    this.frames = 0;
    this.fpsClock = 0;
    this.fps = 0;
    this.pendingCapture = null;
    this.running = false;

    this._onResize = () => this.resize();
    window.addEventListener('resize', this._onResize);
    this.resize();
  }

  _setBackground([inner, outer]) {
    const size = 512;
    const canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;

    const ctx = canvas.getContext('2d');
    const gradient = ctx.createRadialGradient(size / 2, size * 0.46, 0, size / 2, size / 2, size * 0.72);
    gradient.addColorStop(0, inner);
    gradient.addColorStop(1, outer);
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, size, size);

    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;

    this.scene.background?.dispose?.();
    this.scene.background = texture;
  }

  _buildComposer() {
    const size = new THREE.Vector2();
    this.renderer.getSize(size);

    this.composer = new EffectComposer(this.renderer);
    this.composer.addPass(new RenderPass(this.scene, this.camera));

    this.bloom = new UnrealBloomPass(size, 0.9, 0.62, 0.40);
    this.composer.addPass(this.bloom);

    this.grade = new ShaderPass(GradeShader);
    this.composer.addPass(this.grade);

    this.composer.addPass(new OutputPass());
  }

  applyPalette(key) {
    const palette = PALETTES[key] ?? PALETTES.ember;
    this.settings.palette = key;
    this.orb.setPalette(palette);
    this._setBackground(palette.background);
  }

  resetCamera() {
    this.camera.position.copy(DEFAULT_CAMERA);
    this.controls.target.set(0, DEFAULT_CAMERA.y, 0);
    this.controls.update();
  }

  resize() {
    const width = this.container.clientWidth || window.innerWidth;
    const height = this.container.clientHeight || window.innerHeight;

    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();

    this.renderer.setSize(width, height, false);
    this.composer.setSize(width, height);
  }

  /** Resolves with a PNG Blob captured from the next rendered frame. */
  capture() {
    return new Promise((resolve) => {
      this.pendingCapture = resolve;
    });
  }

  start(audioEngine) {
    this.audio = audioEngine;
    this.running = true;
    this.renderer.setAnimationLoop(() => this._frame());
  }

  stop() {
    this.running = false;
    this.renderer.setAnimationLoop(null);
  }

  _frame() {
    this.timer.update();
    const dt = Math.min(this.timer.getDelta(), 1 / 20);
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
      this.canvas.toBlob((blob) => resolve(blob), 'image/png');
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

  dispose() {
    this.stop();
    window.removeEventListener('resize', this._onResize);
    this.controls.dispose();
    this.orb.dispose();
    this.composer.dispose();
    this.renderer.dispose();
  }
}
