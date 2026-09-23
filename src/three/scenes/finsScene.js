/**
 * Иридесцентный фон-«рёбра» (flowing fins) — фирменный фон InCellCorp на всю
 * страницу. Fullscreen-quad ShaderMaterial: вертикальные «пряди», изогнутые
 * текущим fbm-шумом (органично, не механическая сетка), мягкое аддитивное
 * свечение со спектральным отливом, приглушённое + виньетка (контент читаем).
 * Порт подхода docs/design_transfer/09 (backgroundScene) в JS.
 *
 * Экспорт: createFinsScene() → sceneModule для ThreeStage (fullscreen:true).
 */

const VERTEX_SHADER = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = vec4(position.xy, 0.0, 1.0);
  }
`;

const FRAGMENT_SHADER = /* glsl */ `
  precision highp float;
  uniform vec2 uResolution;
  uniform float uTime;
  uniform vec2 uPointer;
  uniform float uIntensity;
  varying vec2 vUv;

  // Хеш + 2D value-noise (мерцание прядей и узлы хаотичной ломаной).
  float hash21(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
  }
  float noise2(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = hash21(i);
    float b = hash21(i + vec2(1.0, 0.0));
    float c = hash21(i + vec2(0.0, 1.0));
    float d = hash21(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
  }

  /**
   * ХАОТИЧНАЯ ЛОМАНАЯ. Узлы решётки берут СЛУЧАЙНЫЕ значения (hash), а между
   * узлами идёт ЛИНЕЙНАЯ интерполяция — без smoothstep. Отсюда:
   *  - излом на каждом узле, под случайным углом (а не регулярный зигзаг);
   *  - соседние рёбра ломаются по-разному (значения зависят и от x).
   * Это характер GPThub поверх структуры эталона: те же тонкие рёбра, но
   * «сломанные» хаотично, а не изогнутые гладким потоком.
   */
  float chaosCrease(vec2 p, float segs, float seed) {
    float s = p.y * segs;
    float i = floor(s);
    float t = fract(s);              // ЛИНЕЙНО ⇒ излом на границах узлов
    float xc = p.x * 2.2 + seed;
    float xi = floor(xc);
    float xt = fract(xc);
    float a0 = hash21(vec2(xi, i + seed * 7.0));
    float a1 = hash21(vec2(xi + 1.0, i + seed * 7.0));
    float b0 = hash21(vec2(xi, i + 1.0 + seed * 7.0));
    float b1 = hash21(vec2(xi + 1.0, i + 1.0 + seed * 7.0));
    float v0 = mix(a0, a1, xt);
    float v1 = mix(b0, b1, xt);
    return mix(v0, v1, t) - 0.5;
  }

  void main() {
    vec2 uv = vUv;
    float aspect = uResolution.x / max(1.0, uResolution.y);
    vec2 p = vec2(uv.x * aspect, uv.y);
    p.x += uPointer.x * 0.06;
    p.y += uPointer.y * 0.03;

    // Три масштаба хаотичных изломов: крупные складки → средние → мелкие зазубрины.
    // Амплитуды намеренно скромные: при большом сдвиге фаза менялась быстрее
    // пикселя, pow(|sin|,13) съедался алиасингом — и рёбра местами ПРОПАДАЛИ.
    float f = chaosCrease(vec2(p.x, uv.y + uTime * 0.030), 5.0, 1.0) * 1.5;
    f += chaosCrease(vec2(p.x * 2.3, uv.y - uTime * 0.048), 11.0, 5.0) * 0.65;
    f += chaosCrease(vec2(p.x * 4.1, uv.y + uTime * 0.075), 23.0, 9.0) * 0.28;

    // Тонкие вертикальные рёбра — структура эталона: pow(|sin|, 13).
    // Плотность ФИКСИРОВАНА (58), как у них: с aspect-коррекцией на 16:9
    // выходило ~68 рёбер, т.е. заметно тоньше и гуще эталона.
    float fins = 58.0;
    float phase = uv.x * 3.14159265 * fins + f * 2.2;
    float stripe = pow(abs(sin(phase)), 13.0);

    // Индекс ребра — ключ для мерцания «по прядям».
    float idx = floor(phase / 3.14159265);

    // Мерцание по прядям (живость). Пол 0.6: ниже пряди начинали пропадать.
    float vary = 0.6 + 0.4 * noise2(vec2(idx * 0.6, uTime * 0.5 + idx));

    // Горизонтальная волна яркости. ДВА страховочных момента:
    //  1) частота 5.2 (было 3.4 — меньше периода на всю ширину, из-за чего весь
    //     экран разом уходил в отрицательную полуволну синуса);
    //  2) clamp снизу — band НИКОГДА не обнуляется, поэтому фон не может погаснуть
    //     целиком (раньше при band<=0 аддитивное свечение уходило в ноль).
    float band = 0.45 + 0.55 * sin(uv.x * 5.2 - uTime * 0.22 + f * 1.6);
    band = clamp(band, 0.65, 1.0);

    // Цвет — ровно модель эталона: ТРИ цвета (cyan → iris → magenta), смешанные
    // по координате потока. У нас была 5-стоповая палитра С РОЗОВЫМ (#FF7AD9) —
    // отсюда чужой розовый отлив, которого у них нет.
    vec3 cIris    = vec3(0.369, 0.482, 1.000); // #5E7BFF
    vec3 cMagenta = vec3(0.706, 0.361, 1.000); // #B45CFF
    vec3 cCyan    = vec3(0.239, 0.851, 0.737); // #3DD9BC
    float ct = fract(f * 0.5 + uv.y * 0.4 + 0.5);
    vec3 col = mix(cCyan, cIris, smoothstep(0.0, 0.5, ct));
    col = mix(col, cMagenta, smoothstep(0.5, 1.0, ct));

    // Виньетка эталона: пик по центру экрана, к верху и низу — в ноль; левая
    // колонка (текст героя) и края притушены, чтобы фон не спорил с текстом.
    float vy = smoothstep(0.02, 0.5, uv.y) * smoothstep(1.0, 0.5, uv.y);
    float vx = smoothstep(0.0, 0.42, uv.x) * smoothstep(1.05, 0.5, uv.x) + 0.15;
    float vig = clamp(vy * vx, 0.0, 1.0);

    float b = stripe * vary * band * vig * uIntensity;
    // Аддитивное свечение над чёрной страницей (прозрачный canvas).
    gl_FragColor = vec4(col * b, b);
  }
`;

export function createFinsScene() {
  return {
    setup({ THREE, renderer, width, height }) {
      const scene = new THREE.Scene();
      const camera = new THREE.Camera();
      const geometry = new THREE.PlaneGeometry(2, 2);

      const uniforms = {
        uResolution: { value: new THREE.Vector2(width, height) },
        uTime: { value: 0 },
        uPointer: { value: new THREE.Vector2(0, 0) },
        // Эталон держит фон тусклым (0.2). Рёбра тонкие (pow 13) и рваные, т.е.
        // покрытие площади маленькое — можно светить заметно ярче, не убивая
        // читаемость: виньетка гасит фон ровно там, где идёт текст.
        uIntensity: { value: 0.70 },
      };

      const material = new THREE.ShaderMaterial({
        vertexShader: VERTEX_SHADER,
        fragmentShader: FRAGMENT_SHADER,
        uniforms,
        transparent: true,
        depthWrite: false,
        depthTest: false,
        blending: THREE.AdditiveBlending,
      });

      const mesh = new THREE.Mesh(geometry, material);
      scene.add(mesh);

      return {
        update({ elapsed, pointer }) {
          uniforms.uTime.value = elapsed;
          uniforms.uPointer.value.set(pointer.x, pointer.y);
        },
        resize(w, h) {
          uniforms.uResolution.value.set(w, h);
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
