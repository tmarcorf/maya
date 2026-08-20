/**
 * GLSL do orb — referência do print do usuário: esfera escura de vidro
 * envolta por um anel de partículas com gradiente rosa → lavanda → azul.
 *
 * Núcleo: noise simplex (Ashima) sutil + fresnel rim tingido pelo
 * gradiente. Partículas: órbita calculada NA GPU — cada partícula tem
 * ponto unitário no anel (aP0), tangente (aAxis), fase, velocidade e
 * raio; a energia (nível de áudio) acelera a órbita e expande o anel.
 */

export const ORB_CORE_VERTEX_SHADER = /* glsl */ `
  uniform float uTime;
  uniform float uAmplitude;

  varying vec3 vWorldPos;
  varying vec3 vNormal;
  varying vec3 vViewDir;
  varying float vDisplacement;

  vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
  vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
  vec4 permute(vec4 x) { return mod289(((x * 34.0) + 1.0) * x); }
  vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }

  float snoise(vec3 v) {
    const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
    const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);

    vec3 i = floor(v + dot(v, C.yyy));
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

    vec4 norm = taylorInvSqrt(vec4(
      dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3)));
    p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;

    vec4 m = max(0.6 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
    m = m * m;
    return 42.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
  }

  void main() {
    float noise = snoise(normal * 2.2 + uTime * 0.05);
    float displacement = noise * uAmplitude;
    vec3 displaced = position + normal * displacement;

    vec4 world = modelMatrix * vec4(displaced, 1.0);

    vWorldPos = world.xyz;
    vNormal = normalize(normalMatrix * normal);
    vViewDir = normalize(cameraPosition - world.xyz);
    vDisplacement = displacement;

    gl_Position = projectionMatrix * viewMatrix * world;
  }
`;

export const ORB_CORE_FRAGMENT_SHADER = /* glsl */ `
  uniform vec3 uColorTop;
  uniform vec3 uColorBottom;
  uniform float uRimPower;
  uniform float uEnergy;

  varying vec3 vWorldPos;
  varying vec3 vNormal;
  varying vec3 vViewDir;
  varying float vDisplacement;

  void main() {
    // Em WebGL o espaço de derivadas segue a convenção GL (y cresce
    // para CIMA na janela): dFdy aponta para +y mundo, então a normal
    // para a câmera é cross(dFdx, dFdy). A ordem contrária inverte a
    // normal e acende o rim na esfera inteira.
    vec3 normal = normalize(cross(dFdx(vWorldPos), dFdy(vWorldPos)));
    float facing = max(dot(normal, normalize(vViewDir)), 0.0);
    float fresnel = pow(1.0 - facing, uRimPower);

    // Vidro escuro: quase sumido no fundo — quem brilha é o anel.
    vec3 base = vec3(0.05, 0.048, 0.08);
    vec3 rimColor = mix(uColorBottom, uColorTop, smoothstep(-1.0, 1.0, normal.y));

    vec3 color = base * (0.35 + 0.4 * facing) + vDisplacement * 0.12;
    // O rim ecoa o gradiente do anel e esquenta com a energia (fala).
    color += rimColor * fresnel * (0.7 + uEnergy * 1.2);
    color += rimColor * fresnel * fresnel * 0.2;

    gl_FragColor = vec4(color, 1.0);
  }
`;

export const ORB_PARTICLES_VERTEX_SHADER = /* glsl */ `
  attribute vec3 aP0;      // ponto unitário no anel (já inclinado)
  attribute vec3 aAxis;    // tangente unitária (⊥ aP0) — direção da órbita
  attribute float aPhase;  // fase inicial 0..2π
  attribute float aSpeed;  // 0.6..1.6
  attribute float aRadius; // raio base do anel
  attribute float aSize;   // 0.6..1.4

  uniform float uTime;
  uniform float uEnergy; // 0..1 — acelera a órbita e expande o anel

  varying float vGradient;

  void main() {
    float speed = aSpeed * (0.6 + uEnergy * 4.0);
    float theta = aPhase + uTime * speed;
    float r = aRadius * (1.0 + uEnergy * 0.1);
    vec3 pos = (aP0 * cos(theta) + aAxis * sin(theta)) * r;

    vec4 world = modelMatrix * vec4(pos, 1.0);
    // Gradiente espacial: rosa no alto, azul embaixo (igual ao print).
    vGradient = smoothstep(-0.9, 0.9, world.y);

    vec4 mv = modelViewMatrix * vec4(pos, 1.0);
    // ~1.5-4 px em idle, ~4-12 px com energia total (distância ~5).
    gl_PointSize = aSize * (1.0 + uEnergy * 2.0) * (17.0 / -mv.z);
    gl_Position = projectionMatrix * mv;
  }
`;

export const ORB_PARTICLES_FRAGMENT_SHADER = /* glsl */ `
  uniform vec3 uColorTop;
  uniform vec3 uColorBottom;
  uniform float uEnergy;

  varying float vGradient;

  void main() {
    float d = length(gl_PointCoord - 0.5);
    float alpha = smoothstep(0.5, 0.0, d);
    alpha = pow(alpha, 1.8); // núcleo do ponto mais denso que a borda
    // Alpha contido: blending aditivo SOMA — partículas sobrepostas não
    // podem saturar os canais para branco (referência do print).
    vec3 color = mix(uColorBottom, uColorTop, vGradient);
    gl_FragColor = vec4(color, alpha * (0.9 + uEnergy * 0.1));
  }
`;
