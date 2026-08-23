// Ashima Arts / Stefan Gustavson simplex noise (MIT), plus the displacement
// function shared by the filament lines and the occluding core so both deform
// identically -- the core must never poke through the lines.
export const NOISE_GLSL = /* glsl */ `
vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 permute(vec4 x) { return mod289(((x * 34.0) + 10.0) * x); }
vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }

float snoise(vec3 v) {
  const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
  const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);

  vec3 i  = floor(v + dot(v, C.yyy));
  vec3 x0 = v - i + dot(i, C.xxx);

  vec3 g = step(x0.yzx, x0.xyz);
  vec3 l = 1.0 - g;
  vec3 i1 = min(g.xyz, l.zxy);
  vec3 i2 = max(g.xyz, l.zxy);

  vec3 x1 = x0 - i1 + C.xxx;
  vec3 x2 = x0 - i2 + C.yyy;
  vec3 x3 = x0 - D.yyy;

  i = mod289(i);
  vec4 p = permute(permute(permute(
             i.z + vec4(0.0, i1.z, i2.z, 1.0))
           + i.y + vec4(0.0, i1.y, i2.y, 1.0))
           + i.x + vec4(0.0, i1.x, i2.x, 1.0));

  float n_ = 0.142857142857;
  vec3 ns = n_ * D.wyz - D.xzx;

  vec4 j = p - 49.0 * floor(p * ns.z * ns.z);

  vec4 x_ = floor(j * ns.z);
  vec4 y_ = floor(j - 7.0 * x_);

  vec4 x = x_ * ns.x + ns.yyyy;
  vec4 y = y_ * ns.x + ns.yyyy;
  vec4 h = 1.0 - abs(x) - abs(y);

  vec4 b0 = vec4(x.xy, y.xy);
  vec4 b1 = vec4(x.zw, y.zw);

  vec4 s0 = floor(b0) * 2.0 + 1.0;
  vec4 s1 = floor(b1) * 2.0 + 1.0;
  vec4 sh = -step(h, vec4(0.0));

  vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
  vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;

  vec3 p0 = vec3(a0.xy, h.x);
  vec3 p1 = vec3(a0.zw, h.y);
  vec3 p2 = vec3(a1.xy, h.z);
  vec3 p3 = vec3(a1.zw, h.w);

  vec4 norm = taylorInvSqrt(vec4(dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3)));
  p0 *= norm.x;
  p1 *= norm.y;
  p2 *= norm.z;
  p3 *= norm.w;

  vec4 m = max(0.5 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
  m = m * m;
  return 105.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
}
`;

// uSpectrum: 1D texture of smoothed FFT magnitudes, sampled by longitude so the
// silhouette dances like a radial equaliser. uWave adds a fast time-domain jitter.
export const DISPLACE_GLSL = /* glsl */ `
uniform sampler2D uSpectrum;
uniform float uTime;
uniform float uRadius;
uniform float uBass;
uniform float uMid;
uniform float uTreble;
uniform float uLevel;
uniform float uBeat;
uniform float uTurbulence;
uniform float uDetail;

float spectrumAt(vec3 dir) {
  // Longitude -> [0,1]; the extra latitude fold keeps the poles from going flat.
  float lon = atan(dir.z, dir.x) / 6.2831853 + 0.5;
  float lat = acos(clamp(dir.y, -1.0, 1.0)) / 3.14159265;
  float a = texture2D(uSpectrum, vec2(lon, 0.5)).r;
  float b = texture2D(uSpectrum, vec2(fract(lon * 2.0 + lat * 0.5), 0.5)).r;
  return mix(a, b, 0.35);
}

// Returns the radial offset (in world units) for a point on the unit sphere.
// Kept small on purpose: the reference silhouette is finely serrated, not lobed.
float radialOffset(vec3 dir) {
  float t = uTime;
  float freq = 2.6 + uDetail * 3.4;

  float n1 = snoise(dir * freq + vec3(0.0, t * 0.22, 0.0));
  float n2 = snoise(dir * freq * 2.6 + vec3(t * 0.35, 0.0, t * -0.2));
  float n3 = snoise(dir * freq * 6.4 - vec3(0.0, t * 0.7, 0.0));
  float n4 = snoise(dir * freq * 13.0 + vec3(t * 1.1, t * 0.4, 0.0));

  float fbm = n1 * 0.52 + n2 * 0.30 * (0.35 + uMid) + n3 * 0.20 * (0.3 + uTreble)
            + n4 * 0.11 * (0.2 + uTreble);

  // Poles are the loudest part of the reference, but only slightly.
  float poleBias = 0.80 + 0.40 * pow(abs(dir.y), 3.0);
  float amp = (0.026 + uBass * 0.070 + uLevel * 0.028) * uTurbulence * poleBias;

  float spec = spectrumAt(dir);
  float spikes = pow(spec, 2.2) * (0.030 + uTreble * 0.055) * uTurbulence;

  return fbm * amp + spikes + uBeat * 0.016;
}

float orbRadius(vec3 dir) {
  float breathe = 1.0 + uLevel * 0.065 + uBeat * 0.028 + sin(uTime * 0.6) * 0.010;
  return uRadius * breathe + radialOffset(dir);
}
`;
