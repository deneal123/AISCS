/**
 * Scene runner — владеет жизненным циклом WebGL, сцены только описывают контент.
 * Порт контракта docs/design_transfer/09 (ThreeStage.ts) в JS.
 *
 * createSceneRunner(canvas, sceneModule, opts) → { dispose } | null (null при
 * сбое инициализации → вызывающий показывает CSS-фолбэк).
 *
 * sceneModule.setup({ THREE, renderer, canvas, width, height, tier }) →
 *   { update(frameInfo), resize?(w,h), render(), dispose() }
 * frameInfo: { dt, elapsed, scroll, pointer:{x,y}, tier }
 */
export function createSceneRunner(canvas, sceneModule, opts) {
  const {
    THREE,
    tier = "full",
    dprCap = 2,
    pointer: usePointer = false,
    scroll: useScroll = false,
    clearColor = 0x000000,
    clearAlpha = 0,
    antialias = true,
    fullscreen = false,
  } = opts || {};

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({
      canvas,
      antialias,
      alpha: clearAlpha < 1,
      powerPreference: "high-performance",
    });
    renderer.setClearColor(clearColor, clearAlpha);
  } catch {
    return null;
  }
  if (!renderer) return null;

  const getSize = () => {
    if (fullscreen) {
      return { w: window.innerWidth, h: window.innerHeight };
    }
    const rect = canvas.parentElement?.getBoundingClientRect?.() ||
      canvas.getBoundingClientRect();
    return { w: Math.max(1, Math.round(rect.width)), h: Math.max(1, Math.round(rect.height)) };
  };

  const applySize = () => {
    const { w, h } = getSize();
    const dpr = Math.min(window.devicePixelRatio || 1, dprCap);
    renderer.setPixelRatio(dpr);
    renderer.setSize(w, h, false);
    return { w, h };
  };

  let size = applySize();

  let handle;
  try {
    handle = sceneModule.setup({
      THREE,
      renderer,
      canvas,
      width: size.w,
      height: size.h,
      tier,
    });
  } catch {
    renderer.dispose?.();
    return null;
  }
  if (!handle) {
    renderer.dispose?.();
    return null;
  }

  // ── Pointer (eased к NDC) ─────────────────────────────────────────────
  const pointer = { x: 0, y: 0 };
  const pointerTarget = { x: 0, y: 0 };
  const onPointerMove = (e) => {
    pointerTarget.x = (e.clientX / window.innerWidth) * 2 - 1;
    pointerTarget.y = -((e.clientY / window.innerHeight) * 2 - 1);
  };
  if (usePointer) window.addEventListener("pointermove", onPointerMove, { passive: true });

  // ── Scroll (0 в зоне → 1 ушёл за верх) ────────────────────────────────
  let scroll = 0;
  const computeScroll = () => {
    if (!useScroll) return 0;
    const rect = canvas.getBoundingClientRect();
    const vh = window.innerHeight || 1;
    // 0, пока центр канваса в вьюпорте; растёт к 1 при уходе вверх.
    const progress = 1 - (rect.bottom / (vh + rect.height));
    return Math.min(1, Math.max(0, progress));
  };

  // ── Pause on hidden / offscreen ───────────────────────────────────────
  let running = true;
  let visible = true;
  const onVisibility = () => {
    running = !document.hidden && visible;
    if (running) loop();
  };
  document.addEventListener("visibilitychange", onVisibility);

  let io = null;
  if ("IntersectionObserver" in window && !fullscreen) {
    io = new IntersectionObserver(
      ([entry]) => {
        visible = entry.isIntersecting;
        running = visible && !document.hidden;
        if (running) loop();
      },
      { threshold: 0 },
    );
    io.observe(canvas);
  }

  // ── Resize (debounced) ────────────────────────────────────────────────
  let resizeRaf = 0;
  const doResize = () => {
    size = applySize();
    handle.resize?.(size.w, size.h);
  };
  const onResize = () => {
    if (resizeRaf) cancelAnimationFrame(resizeRaf);
    resizeRaf = requestAnimationFrame(doResize);
  };
  let ro = null;
  if ("ResizeObserver" in window && !fullscreen && canvas.parentElement) {
    ro = new ResizeObserver(onResize);
    ro.observe(canvas.parentElement);
  } else {
    window.addEventListener("resize", onResize);
  }

  // ── rAF loop ──────────────────────────────────────────────────────────
  let rafId = 0;
  let last = 0;
  let elapsed = 0;
  let looping = false;

  const frame = (now) => {
    if (!running) {
      looping = false;
      return;
    }
    const dt = last ? Math.min(0.05, (now - last) / 1000) : 0.016;
    last = now;
    elapsed += dt;

    if (usePointer) {
      pointer.x += (pointerTarget.x - pointer.x) * Math.min(1, dt * 6);
      pointer.y += (pointerTarget.y - pointer.y) * Math.min(1, dt * 6);
    }
    if (useScroll) scroll = computeScroll();

    try {
      handle.update({ dt, elapsed, scroll, pointer, tier });
      handle.render();
    } catch {
      dispose();
      return;
    }
    rafId = requestAnimationFrame(frame);
  };

  function loop() {
    if (looping || !running) return;
    looping = true;
    last = 0;
    rafId = requestAnimationFrame(frame);
  }

  let disposed = false;
  function dispose() {
    if (disposed) return;
    disposed = true;
    running = false;
    cancelAnimationFrame(rafId);
    if (resizeRaf) cancelAnimationFrame(resizeRaf);
    if (usePointer) window.removeEventListener("pointermove", onPointerMove);
    document.removeEventListener("visibilitychange", onVisibility);
    window.removeEventListener("resize", onResize);
    io?.disconnect();
    ro?.disconnect();
    try {
      handle.dispose?.();
    } catch {
      /* no-op */
    }
    renderer.dispose?.();
  }

  loop();

  return { dispose };
}
