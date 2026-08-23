/**
 * Final grade: vignette, edge chromatic aberration and animated grain.
 * Runs after bloom, before OutputPass (so it works in linear space).
 */
export const GradeShader = {
  name: 'GradeShader',

  uniforms: {
    tDiffuse: { value: null },
    uTime: { value: 0 },
    uVignette: { value: 1.0 },
    uGrain: { value: 0.022 },
    uAberration: { value: 0.0022 },
    uSaturation: { value: 1.12 },
    uLevel: { value: 0 },
  },

  vertexShader: /* glsl */ `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,

  fragmentShader: /* glsl */ `
    uniform sampler2D tDiffuse;
    uniform float uTime;
    uniform float uVignette;
    uniform float uGrain;
    uniform float uAberration;
    uniform float uSaturation;
    uniform float uLevel;

    varying vec2 vUv;

    float hash(vec2 p) {
      return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
    }

    void main() {
      vec2 centered = vUv - 0.5;
      float dist = length(centered);

      // Split the channels radially; scales with loudness so peaks feel unstable.
      float shift = uAberration * (1.0 + uLevel * 2.2) * dist;
      vec3 color = vec3(
        texture2D(tDiffuse, vUv + centered * shift).r,
        texture2D(tDiffuse, vUv).g,
        texture2D(tDiffuse, vUv - centered * shift).b
      );

      float luma = dot(color, vec3(0.2126, 0.7152, 0.0722));
      color = mix(vec3(luma), color, uSaturation);

      float vignette = smoothstep(0.95, 0.20, dist * uVignette);
      color *= mix(1.0, vignette, 0.85);

      // Grain keeps the wide dark areas from banding.
      float grain = hash(vUv * 1024.0 + fract(uTime) * 91.7) - 0.5;
      color += grain * uGrain * (1.0 - luma * 0.6);

      gl_FragColor = vec4(max(color, 0.0), 1.0);
    }
  `,
};
