/**
 * Морф-блоб герой — фирменный «tell» InCellCorp. Порт подхода
 * docs/design_transfer/09 (heroBlobScene.ts) в JS.
 *
 * IcosahedronGeometry, вершины смещаются 3D-simplex-шумом (нормаль
 * пересчитывается через касательные смещения — тень как у объёма), фрагмент —
 * fresnel-rim + спектральная палитра (cyan→iris→violet→magenta→pink) + глянец.
 * Рендер прямой (без пост-обработки) → canvas прозрачный, парит над страницей;
 * свечение даёт fresnel + CSS-halo `.hero-orb::before`.
 *
 * Экспорт: createHeroBlobScene(stateRef) → sceneModule для ThreeStage.
 * stateRef.current может нести { intensity } (0..1) — например затухание на скролле.
 */

const VERTEX_SHADER = /* glsl */ `
  uniform float uTime;
  uniform float uAmp;
  uniform float uFreq;
  uniform float uSpeed;
  uniform float uRadius;

  varying vec3 vNormalW;
  varying vec3 vViewDir;
  varying float vDisp;

  // ── Ashima simplex noise 3D ──
  vec4 permute(vec4 x){ return mod(((x*34.0)+1.0)*x, 289.0); }
  vec4 taylorInvSqrt(vec4 r){ return 1.79284291400159 - 0.85373472095314 * r; }
  float snoise(vec3 v){
    const vec2 C = vec2(1.0/6.0, 1.0/3.0);
    const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
    vec3 i  = floor(v + dot(v, C.yyy));
    vec3 x0 = v - i + dot(i, C.xxx);
    vec3 g = step(x0.yzx, x0.xyz);
    vec3 l = 1.0 - g;
    vec3 i1 = min(g.xyz, l.zxy);
    vec3 i2 = max(g.xyz, l.zxy);
    vec3 x1 = x0 - i1 + 1.0 * C.xxx;
    vec3 x2 = x0 - i2 + 2.0 * C.xxx;
    vec3 x3 = x0 - 1.0 + 3.0 * C.xxx;
    i = mod(i, 289.0);
    vec4 p = permute(permute(permute(
              i.z + vec4(0.0, i1.z, i2.z, 1.0))
            + i.y + vec4(0.0, i1.y, i2.y, 1.0))
            + i.x + vec4(0.0, i1.x, i2.x, 1.0));
    float n_ = 1.0/7.0;
    vec3 ns = n_ * D.wyz - D.xzx;
    vec4 j = p - 49.0 * floor(p * ns.z *ns.z);
    vec4 x_ = floor(j * ns.z);
    vec4 y_ = floor(j - 7.0 * x_);
    vec4 x = x_ *ns.x + ns.yyyy;
    vec4 y = y_ *ns.x + ns.yyyy;
    vec4 h = 1.0 - abs(x) - abs(y);
    vec4 b0 = vec4(x.xy, y.xy);
    vec4 b1 = vec4(x.zw, y.zw);
    vec4 s0 = floor(b0)*2.0 + 1.0;
    vec4 s1 = floor(b1)*2.0 + 1.0;
    vec4 sh = -step(h, vec4(0.0));
    vec4 a0 = b0.xzyw + s0.xzyw*sh.xxyy;
    vec4 a1 = b1.xzyw + s1.xzyw*sh.zzww;
    vec3 p0 = vec3(a0.xy, h.x);
    vec3 p1 = vec3(a0.zw, h.y);
    vec3 p2 = vec3(a1.xy, h.z);
    vec3 p3 = vec3(a1.zw, h.w);
    vec4 norm = taylorInvSqrt(vec4(dot(p0,p0), dot(p1,p1), dot(p2,p2), dot(p3,p3)));
    p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
    vec4 m = max(0.6 - vec4(dot(x0,x0), dot(x1,x1), dot(x2,x2), dot(x3,x3)), 0.0);
    m = m * m;
    return 42.0 * dot(m*m, vec4(dot(p0,x0), dot(p1,x1), dot(p2,x2), dot(p3,x3)));
  }

  float fbm(vec3 p){
    float f = 0.0;
    float amp = 0.5;
    for (int i = 0; i < 4; i++) {
      f += amp * snoise(p);
      p *= 2.0;
      amp *= 0.5;
    }
    return f;
  }

  float displace(vec3 p){
    return fbm(p * uFreq + vec3(0.0, 0.0, uTime * uSpeed));
  }

  vec3 displacedPosition(vec3 pos){
    vec3 nor = normalize(pos);
    return pos + nor * (displace(pos) * uAmp);
  }

  void main(){
    vec3 nor = normalize(position);
    // Касательный базис для пересчёта нормали.
    vec3 t1 = normalize(cross(nor, vec3(0.0, 1.0, 0.0) + vec3(1e-4)));
    vec3 t2 = cross(nor, t1);
    float e = 0.15;
    vec3 pA = normalize(position + t1 * e) * uRadius;
    vec3 pB = normalize(position + t2 * e) * uRadius;

    vec3 dp0 = displacedPosition(position);
    vec3 dpA = displacedPosition(pA);
    vec3 dpB = displacedPosition(pB);
    vec3 newNormal = normalize(cross(dpA - dp0, dpB - dp0));

    vDisp = displace(position);
    vNormalW = normalize(mat3(modelMatrix) * newNormal);
    vec4 worldPos = modelMatrix * vec4(dp0, 1.0);
    vViewDir = normalize(cameraPosition - worldPos.xyz);

    gl_Position = projectionMatrix * viewMatrix * worldPos;
  }
`;

const FRAGMENT_SHADER = /* glsl */ `
  precision highp float;
  uniform float uIntensity;
  uniform float uTime;

  varying vec3 vNormalW;
  varying vec3 vViewDir;
  varying float vDisp;

  // Палитра эталона: iris → cyan → violet → magenta. РОЗОВОГО нет — у них про
  // блоб прямо сказано «never warm/white», а у нас в рампе стоял pink #FF7AD9.
  vec3 spectral(float t){
    t = fract(t);
    vec3 c0 = vec3(0.37, 0.48, 1.00); // iris
    vec3 c1 = vec3(0.30, 0.80, 0.92); // cyan (голубее)
    vec3 c2 = vec3(0.49, 0.36, 1.00); // violet
    vec3 c3 = vec3(0.71, 0.36, 1.00); // magenta
    if (t < 0.33) return mix(c0, c1, t / 0.33);
    if (t < 0.66) return mix(c1, c2, (t - 0.33) / 0.33);
    return mix(c2, c3, (t - 0.66) / 0.34);
  }

  void main(){
    vec3 N = normalize(vNormalW);
    vec3 V = normalize(vViewDir);
    float ndv = clamp(dot(N, V), 0.0, 1.0);
    float fres = pow(1.0 - ndv, 3.0);

    vec3 L = normalize(vec3(0.5, 0.8, 0.6));
    float key = clamp(dot(N, L), 0.0, 1.0);

    // Тонкоплёночный оттенок: по углу взгляда + смещению вершины.
    float t = 0.05 + ndv * 0.22 + vDisp * 0.70 + fres * 0.18 + uTime * 0.015;
    vec3 irid = spectral(t);

    // Тёмное стеклянное тело + иридесцентный отлив + яркая fresnel-кромка.
    vec3 base = vec3(0.012, 0.018, 0.042);
    vec3 color = base + irid * (0.12 + fres * 0.95);
    color += irid * pow(fres, 1.5) * 1.05;
    color += irid * pow(key, 2.0) * 0.14;

    // Блик — Blinn-Phong, экспонента 48 и ХОЛОДНЫЙ оттенок (0.85,0.92,1.0).
    // Было: Phong с экспонентой 24 и ЧИСТО БЕЛЫЙ vec3(spec) — отсюда широкие
    // белые засветы, которых у эталона нет.
    vec3 H = normalize(L + V);
    float spec = pow(max(dot(N, H), 0.0), 48.0);
    color += vec3(0.85, 0.92, 1.0) * spec * 0.55;

    float alpha = (0.35 + 0.65 * fres) * uIntensity;
    gl_FragColor = vec4(color, alpha);
  }
`;

export function createHeroBlobScene(stateRef) {
  return {
    setup({ THREE, renderer, width, height, tier }) {
      const scene = new THREE.Scene();
      // Кадрирование как в эталоне: fov 42, камера дальше. Видимый размер орба
      // ∝ radius / (z · tan(fov/2)); было fov 45 / z 4.2 / r 1.4 → 0.805, тогда
      // как у эталона (fov 42 / z 5.4 / r 1.18) → 0.569, т.е. наш орб был на ~40%
      // крупнее. Геометрию (radius 1.4, низкий detail = фасеточность) НЕ трогаем —
      // это характер GPThub; выравниваем только кадр.
      const camera = new THREE.PerspectiveCamera(42, width / height, 0.1, 100);
      camera.position.set(0, 0, 6.4);

      const radius = 1.4;
      const detail = tier === "reduced" ? 4 : 6;
      const geometry = new THREE.IcosahedronGeometry(radius, detail);

      const uniforms = {
        uTime: { value: 0 },
        uAmp: { value: 0.42 },
        uFreq: { value: 0.9 },
        uSpeed: { value: 0.35 },
        uRadius: { value: radius },
        uIntensity: { value: 1 },
      };

      const material = new THREE.ShaderMaterial({
        vertexShader: VERTEX_SHADER,
        fragmentShader: FRAGMENT_SHADER,
        uniforms,
        transparent: true,
        depthWrite: false,
      });

      const mesh = new THREE.Mesh(geometry, material);
      scene.add(mesh);

      return {
        update({ elapsed, pointer, scroll }) {
          uniforms.uTime.value = elapsed;
          const intensity = (stateRef?.current?.intensity ?? 1) * (1 - scroll * 0.85);
          uniforms.uIntensity.value = Math.max(0, intensity);
          // Медленное вращение + наклон к курсору.
          mesh.rotation.y = elapsed * 0.12 + pointer.x * 0.4;
          mesh.rotation.x = pointer.y * 0.3 + Math.sin(elapsed * 0.15) * 0.08;
        },
        resize(w, h) {
          camera.aspect = w / h;
          camera.updateProjectionMatrix();
        },
        render() {
          renderer.render(scene, camera);
        },
        dispose() {
          geometry.dispose();
          material.dispose();
        },
      };
    },
  };
}
