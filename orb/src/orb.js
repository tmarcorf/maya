import * as THREE from 'three';
import { NOISE_GLSL, DISPLACE_GLSL } from './shaders/noise.js';

const SPECTRUM_BINS = 256;

/**
 * The look is built from three stacked layers:
 *   1. an opaque, near-black core that occludes the far hemisphere
 *   2. dense meridian filaments blended additively (the visible orb)
 *   3. additive flares where the meridians converge at the poles
 * All layers share orbRadius() from noise.js so they deform as one surface.
 */
export class Orb {
  constructor({ meridians = 260, segments = 190, rings = 34 } = {}) {
    this.group = new THREE.Group();
    this.radius = 1;
    this.spin = 0;

    this.spectrumData = new Uint8Array(SPECTRUM_BINS);
    this.spectrumTexture = new THREE.DataTexture(
      this.spectrumData,
      SPECTRUM_BINS,
      1,
      THREE.RedFormat,
      THREE.UnsignedByteType
    );
    this.spectrumTexture.wrapS = THREE.RepeatWrapping;
    this.spectrumTexture.minFilter = THREE.LinearFilter;
    this.spectrumTexture.magFilter = THREE.LinearFilter;
    this.spectrumTexture.needsUpdate = true;

    this.uniforms = {
      uSpectrum: { value: this.spectrumTexture },
      uTime: { value: 0 },
      uRadius: { value: this.radius },
      uBass: { value: 0 },
      uMid: { value: 0 },
      uTreble: { value: 0 },
      uLevel: { value: 0 },
      uBeat: { value: 0 },
      uTurbulence: { value: 1 },
      uDetail: { value: 0.5 },
      uOpacity: { value: 1 },
      uRimPower: { value: 2.0 },
      uColorTop: { value: new THREE.Color(0xff3d10) },
      uColorUpper: { value: new THREE.Color(0xff6a4a) },
      uColorMid: { value: new THREE.Color(0x9d5ad8) },
      uColorLower: { value: new THREE.Color(0x4f7bf0) },
      uColorBottom: { value: new THREE.Color(0x2ec5ff) },
    };

    this.core = this._buildCore();
    this.filaments = this._buildFilaments(meridians, segments);
    this.rings = this._buildRings(rings, Math.max(96, meridians >> 1));
    this.flares = this._buildFlares();

    this.group.add(this.core, this.filaments, this.rings, ...this.flares);
  }

  // ---------------------------------------------------------------- geometry

  /** Meridian arcs, pole to pole, as disconnected segment pairs. */
  _buildFilaments(meridians, segments) {
    const pairs = segments - 1;
    const vertexCount = meridians * pairs * 2;
    const positions = new Float32Array(vertexCount * 3);
    const seeds = new Float32Array(vertexCount);

    let p = 0;
    let s = 0;
    for (let m = 0; m < meridians; m++) {
      // Jitter each meridian slightly so the weave never looks machined.
      const phi = (m / meridians) * Math.PI * 2 + (Math.random() - 0.5) * 0.012;
      const seed = Math.random();
      const cosPhi = Math.cos(phi);
      const sinPhi = Math.sin(phi);

      for (let j = 0; j < pairs; j++) {
        const t0 = (j / pairs) * Math.PI;
        const t1 = ((j + 1) / pairs) * Math.PI;

        positions[p++] = Math.sin(t0) * cosPhi;
        positions[p++] = Math.cos(t0);
        positions[p++] = Math.sin(t0) * sinPhi;

        positions[p++] = Math.sin(t1) * cosPhi;
        positions[p++] = Math.cos(t1);
        positions[p++] = Math.sin(t1) * sinPhi;

        seeds[s++] = seed;
        seeds[s++] = seed;
      }
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('aSeed', new THREE.BufferAttribute(seeds, 1));

    this.filamentMaterial = this._makeLineMaterial(1.0);
    const lines = new THREE.LineSegments(geometry, this.filamentMaterial);
    lines.frustumCulled = false;
    return lines;
  }

  /** A few latitude rings: the horizontal wisps visible near the rim. */
  _buildRings(ringCount, resolution) {
    const vertexCount = ringCount * resolution * 2;
    const positions = new Float32Array(vertexCount * 3);
    const seeds = new Float32Array(vertexCount);

    let p = 0;
    let s = 0;
    for (let r = 0; r < ringCount; r++) {
      // Bias rings toward the poles, where the reference shows the most texture.
      const u = (r + 0.5) / ringCount;
      const bias = Math.sign(u - 0.5) * 0.5 * Math.pow(Math.abs(u - 0.5) * 2, 0.7);
      const theta = Math.PI * (0.5 + bias);
      const sinT = Math.sin(theta);
      const cosT = Math.cos(theta);
      const seed = Math.random();

      for (let j = 0; j < resolution; j++) {
        const a = (j / resolution) * Math.PI * 2;
        const b = ((j + 1) / resolution) * Math.PI * 2;

        positions[p++] = sinT * Math.cos(a);
        positions[p++] = cosT;
        positions[p++] = sinT * Math.sin(a);

        positions[p++] = sinT * Math.cos(b);
        positions[p++] = cosT;
        positions[p++] = sinT * Math.sin(b);

        seeds[s++] = seed;
        seeds[s++] = seed;
      }
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('aSeed', new THREE.BufferAttribute(seeds, 1));

    this.ringMaterial = this._makeLineMaterial(0.34);
    const lines = new THREE.LineSegments(geometry, this.ringMaterial);
    lines.frustumCulled = false;
    return lines;
  }

  _buildCore() {
    const geometry = new THREE.SphereGeometry(1, 200, 130);

    this.coreMaterial = new THREE.ShaderMaterial({
      uniforms: this.uniforms,
      vertexShader: /* glsl */ `
        ${NOISE_GLSL}
        ${DISPLACE_GLSL}

        varying float vLat;
        varying float vRim;

        void main() {
          vec3 dir = normalize(position);
          vLat = dir.y;

          // Sit just inside the filaments so they are never depth-clipped.
          vec3 displaced = dir * orbRadius(dir) * 0.962;
          vec4 world = modelMatrix * vec4(displaced, 1.0);

          vec3 worldNormal = normalize(mat3(modelMatrix) * dir);
          vRim = 1.0 - abs(dot(worldNormal, normalize(cameraPosition - world.xyz)));

          gl_Position = projectionMatrix * viewMatrix * world;
        }
      `,
      fragmentShader: /* glsl */ `
        uniform vec3 uColorTop;
        uniform vec3 uColorMid;
        uniform vec3 uColorBottom;
        uniform float uLevel;
        uniform float uBass;

        varying float vLat;
        varying float vRim;

        void main() {
          float t = clamp(vLat * 0.5 + 0.5, 0.0, 1.0);
          vec3 tint = t > 0.5
            ? mix(uColorMid, uColorTop, smoothstep(0.5, 1.0, t))
            : mix(uColorBottom, uColorMid, smoothstep(0.0, 0.5, t));

          // Barely-lit interior haze, brightest under the poles like the reference.
          // Deliberately far below the bloom threshold so the core stays dark.
          float haze = 0.008 + 0.042 * pow(abs(vLat), 4.0) + 0.016 * pow(vRim, 3.0);
          haze *= 0.60 + uLevel * 0.45 + uBass * 0.28;

          gl_FragColor = vec4(tint * haze + vec3(0.002, 0.004, 0.010), 1.0);
        }
      `,
      transparent: false,
      depthWrite: true,
    });

    const mesh = new THREE.Mesh(geometry, this.coreMaterial);
    mesh.frustumCulled = false;
    return mesh;
  }

  /**
   * Shared additive line material. The uniform holder objects are reused by
   * reference, so writing this.uniforms.uTime.value updates every layer.
   */
  _makeLineMaterial(intensityScale) {
    return new THREE.ShaderMaterial({
      uniforms: Object.assign({}, this.uniforms, { uIntensity: { value: intensityScale } }),
      vertexShader: /* glsl */ `
        ${NOISE_GLSL}
        ${DISPLACE_GLSL}

        attribute float aSeed;

        varying float vLat;
        varying float vRim;
        varying float vSeed;
        varying float vPush;

        void main() {
          vec3 dir = normalize(position);
          float r = orbRadius(dir);

          vLat = dir.y;
          vSeed = aSeed;
          // How far this vertex bulged past the resting radius -> hot spike tips.
          vPush = clamp((r - uRadius) / max(uRadius * 0.28, 0.001), -1.0, 1.5);

          vec4 world = modelMatrix * vec4(dir * r, 1.0);
          vec3 worldNormal = normalize(mat3(modelMatrix) * dir);
          vRim = 1.0 - abs(dot(worldNormal, normalize(cameraPosition - world.xyz)));

          gl_Position = projectionMatrix * viewMatrix * world;
        }
      `,
      fragmentShader: /* glsl */ `
        uniform vec3 uColorTop;
        uniform vec3 uColorUpper;
        uniform vec3 uColorMid;
        uniform vec3 uColorLower;
        uniform vec3 uColorBottom;
        uniform float uOpacity;
        uniform float uIntensity;
        uniform float uRimPower;
        uniform float uLevel;
        uniform float uBeat;

        varying float vLat;
        varying float vRim;
        varying float vSeed;
        varying float vPush;

        vec3 latitudeGradient(float t) {
          vec3 c = mix(uColorBottom, uColorLower, smoothstep(0.00, 0.30, t));
          c = mix(c, uColorMid,    smoothstep(0.28, 0.52, t));
          c = mix(c, uColorUpper,  smoothstep(0.50, 0.76, t));
          c = mix(c, uColorTop,    smoothstep(0.74, 1.00, t));
          return c;
        }

        void main() {
          float t = clamp(vLat * 0.5 + 0.5, 0.0, 1.0);
          vec3 color = latitudeGradient(t);

          // Silhouette-weighted brightness: the core reads dark, the rim burns.
          float rim = pow(clamp(vRim, 0.0, 1.0), uRimPower);
          // Meridians crowd together toward the poles. A broad band carries the
          // heat; only the very tip blows out to white.
          float poleGlow = pow(abs(vLat), 2.5);
          float poleWhite = pow(abs(vLat), 9.0);
          float energy = 0.085 + rim * 1.15 + poleGlow * 0.95;

          // Spike tips run hotter and desaturate toward white.
          float hot = smoothstep(0.15, 1.0, vPush);
          color = mix(color, mix(color, vec3(1.0), 0.72), hot * 0.85);
          color = mix(color, vec3(1.0), poleWhite * 0.70);

          energy *= 0.55 + vSeed * 0.9;                 // per-filament density
          energy *= 0.80 + uLevel * 0.55 + uBeat * 0.5; // loudness
          energy *= uIntensity * uOpacity;

          gl_FragColor = vec4(color, clamp(energy, 0.0, 1.0) * 0.40);
        }
      `,
      transparent: true,
      depthTest: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
  }

  _buildFlares() {
    const size = 256;
    const canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;

    const ctx = canvas.getContext('2d');
    const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    gradient.addColorStop(0.0, 'rgba(255,255,255,1)');
    gradient.addColorStop(0.12, 'rgba(255,255,255,0.55)');
    gradient.addColorStop(0.38, 'rgba(255,255,255,0.14)');
    gradient.addColorStop(1.0, 'rgba(255,255,255,0)');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, size, size);

    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    this.flareTexture = texture;

    const make = (color) => {
      const sprite = new THREE.Sprite(
        new THREE.SpriteMaterial({
          map: texture,
          color,
          transparent: true,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
          depthTest: false,
        })
      );
      sprite.scale.setScalar(0.9);
      return sprite;
    };

    this.flareTop = make(0xff7a3c);
    this.flareBottom = make(0x59d8ff);
    this.flareTop.position.set(0, 1, 0);
    this.flareBottom.position.set(0, -1, 0);
    return [this.flareTop, this.flareBottom];
  }

  // ------------------------------------------------------------------ update

  /**
   * @param {object} audio     frame produced by AudioEngine.read()
   * @param {number} dt        seconds since the previous frame
   * @param {object} settings  live user controls
   */
  update(audio, dt, settings) {
    const u = this.uniforms;

    u.uTime.value += dt * (0.55 + audio.mid * 1.5) * settings.speed;
    u.uBass.value = audio.bass;
    u.uMid.value = audio.mid;
    u.uTreble.value = audio.treble;
    u.uLevel.value = audio.level;
    u.uBeat.value = audio.beat;
    u.uTurbulence.value = settings.turbulence;
    u.uDetail.value = settings.detail;
    u.uRadius.value = this.radius;

    this.spectrumData.set(audio.spectrum);
    this.spectrumTexture.needsUpdate = true;

    // Slow drift, accelerated by the mids, nudged forward on every beat.
    this.spin += dt * (0.06 + audio.mid * 0.35 + audio.beat * 0.6) * settings.speed;
    this.group.rotation.y = this.spin;
    this.group.rotation.z = Math.sin(u.uTime.value * 0.13) * 0.06;

    const rest = this.radius * (1 + audio.level * 0.065);
    this.flareTop.position.y = rest * 1.02;
    this.flareBottom.position.y = -rest * 1.02;
    this.flareTop.scale.setScalar(0.18 + audio.bass * 0.34 + audio.beat * 0.12);
    this.flareBottom.scale.setScalar(0.20 + audio.treble * 0.30 + audio.level * 0.28);
    this.flareTop.material.opacity = (0.10 + audio.bass * 0.28) * settings.glow;
    this.flareBottom.material.opacity = (0.17 + audio.treble * 0.26 + audio.level * 0.26) * settings.glow;
  }

  setPalette(palette) {
    this.uniforms.uColorTop.value.set(palette.top);
    this.uniforms.uColorUpper.value.set(palette.upper);
    this.uniforms.uColorMid.value.set(palette.mid);
    this.uniforms.uColorLower.value.set(palette.lower);
    this.uniforms.uColorBottom.value.set(palette.bottom);
    this.flareTop.material.color.set(palette.flareTop);
    this.flareBottom.material.color.set(palette.flareBottom);
  }

  dispose() {
    this.spectrumTexture.dispose();
    this.flareTexture.dispose();
    for (const mesh of [this.core, this.filaments, this.rings]) {
      mesh.geometry.dispose();
      mesh.material.dispose();
    }
    for (const flare of this.flares) {
      flare.material.dispose();
    }
  }
}
