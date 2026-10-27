// Physical coordinates belong to the numerical model, never the camera or pixels.
export function placementIssue(placement, geometry, clearanceUm = 2) {
  if (!placement) return 'Положение контактов не задано.';
  const contacts = ['electrode', 'reference'].map(key => ({
    name: key === 'electrode' ? 'E1' : 'REF',
    point: ['x_um', 'y_um', 'z_um'].map(axis => placement[key]?.[axis]),
  }));
  for (const { name, point } of contacts) {
    if (point.some(value => !Number.isFinite(value) || Math.abs(value) > 500)) {
      return `${name}: задайте три координаты от −500 до 500 мкм.`;
    }
  }
  if (contacts[0].point.every((value, i) => value === contacts[1].point[i])) {
    return 'E1 и REF должны находиться в разных точках.';
  }
  if (!geometry) return '';
  for (const { name, point } of contacts) {
    for (let i = 0; i < geometry.starts_um.length; i += 1) {
      const start = geometry.starts_um[i], end = geometry.ends_um[i];
      const direction = end.map((value, axis) => value - start[axis]);
      const squaredLength = direction.reduce((sum, value) => sum + value * value, 0);
      if (!(squaredLength > 0)) return 'Геометрия источников недоступна.';
      const fraction = Math.max(0, Math.min(1, direction.reduce((sum, value, axis) => sum + value * (point[axis] - start[axis]), 0) / squaredLength));
      const distance = Math.hypot(...point.map((value, axis) => value - start[axis] - fraction * direction[axis]));
      if (distance <= geometry.diameters_um[i] / 2 + clearanceUm) {
        return `${name} пересекает нейронный источник. Оставьте зазор более ${clearanceUm} мкм от мембраны.`;
      }
    }
  }
  return '';
}

export function reactionAtTime(preview, timeMs, modelVisualization) {
  const controller = preview?.visualization?.reaction || modelVisualization?.reaction;
  if (!preview || !controller || !Number.isFinite(timeMs)) return 0;
  const activity = (preview.spikes || []).reduce((sum, event) => {
    const elapsed = timeMs - event.time_ms;
    return sum + (elapsed >= 0 && elapsed < controller.window_ms ? Math.exp(-elapsed / controller.decay_ms) : 0);
  }, 0);
  return Math.min(1, activity / controller.normalization) * controller.max_angle_rad;
}

const sameRecord = (a, b) => {
  if (a === b) return true;
  if (!a || !b || typeof a !== 'object' || typeof b !== 'object' || Array.isArray(a) !== Array.isArray(b)) return false;
  const keys = Object.keys(a);
  return keys.length === Object.keys(b).length && keys.every(key => Object.hasOwn(b, key) && sameRecord(a[key], b[key]));
};

export function comparisonIssue(reference, configuration, manifest, preview) {
  if (!reference) return '';
  if (!reference.configuration || !configuration) return 'Конфигурация одной из записей недоступна.';
  const first = reference.configuration;
  if (first.model_id !== configuration.model_id || first.duration_ms !== configuration.duration_ms || first.dt_ms !== configuration.dt_ms) {
    return 'Для наложения записей выберите одинаковые модель, длительность и шаг расчёта.';
  }
  if (!reference.manifest?.dynamics_cache?.engine || !manifest?.dynamics_cache?.engine
    || !reference.manifest.units || !manifest.units || !reference.manifest.versions || !manifest.versions
    || !reference.manifest.operator?.source_sha256 || !manifest.operator?.source_sha256) {
    return 'Для сравнения нужны записи с сохранёнными единицами и версиями расчёта. Выберите совместимые завершённые опыты.';
  }
  if (reference.manifest.contract_version !== '1.0' || manifest.contract_version !== '1.0' || !sameRecord(reference.manifest.units, manifest.units)) {
    return 'Версии контракта или единицы записей различаются. Наложение отключено.';
  }
  if (!sameRecord(reference.manifest.dynamics_cache?.engine, manifest.dynamics_cache?.engine)
    || reference.manifest.operator?.source_sha256 !== manifest.operator?.source_sha256
    || !sameRecord(reference.manifest.versions, manifest.versions)) {
    return 'Записи рассчитаны разными версиями численного ядра или оператора. Выберите совместимые опыты.';
  }
  if (preview) {
    const a = reference.time_ms, b = preview.time_ms;
    if (!Array.isArray(a) || !Array.isArray(b) || a.length < 2 || a.length !== b.length
      || Math.abs(a[0]) > 1e-7 || Math.abs(a.at(-1) - configuration.duration_ms) > 1e-6
      || !a.every((time, index) => Number.isFinite(time) && Number.isFinite(b[index]) && Math.abs(time - b[index]) <= 1e-7 && (!index || time > a[index - 1]))) {
      return 'Сохранённые временные оси различаются. Автоматическая интерполяция не выполняется.';
    }
  }
  return '';
}

export function comparisonSceneIssue(reference, configuration) {
  const a = reference?.configuration?.placement?.registration, b = configuration?.placement?.registration;
  if (!a || !b) return 'Для синхронных сцен нужны записи с зарегистрированной геометрией. Наложение совместимых сигналов остаётся доступным.';
  const frameA = Object.fromEntries(Object.entries(a).filter(([key]) => key !== 'surface_anchor'));
  const frameB = Object.fromEntries(Object.entries(b).filter(([key]) => key !== 'surface_anchor'));
  if (!sameRecord(frameA, frameB)) {
    return 'Геометрия или локальные системы координат различаются. Синхронные сцены отключены.';
  }
  return '';
}

export function comparisonReference(run) {
  if (run?.state !== 'completed' || !run.result?.preview) return null;
  return { ...run.result.preview, run_id: run.id, configuration: run.configuration, manifest: run.result.manifest };
}

export function inputEventsAtTime(preview, timeMs, modelVisualization) {
  if (!Array.isArray(preview?.input_events)) return null;
  const windowMs = preview.visualization?.input?.highlight_ms || modelVisualization?.input?.highlight_ms || 2;
  return preview.input_events.filter(event => event.weight_us > 0 && timeMs >= event.time_ms && timeMs - event.time_ms < windowMs);
}

export function responseSeries(preview, modelVisualization) {
  return {
    inputEvents: Array.isArray(preview?.input_events) ? preview.input_events : null,
    motionDegrees: (preview?.time_ms || []).map(time => reactionAtTime(preview, time, modelVisualization) * 180 / Math.PI),
    maxMotionDegrees: (preview?.visualization?.reaction?.max_angle_rad || modelVisualization?.reaction?.max_angle_rad || .25) * 180 / Math.PI,
    maxInputWeightUs: preview?.visualization?.input?.max_event_weight_us || modelVisualization?.input?.max_event_weight_us || .009,
  };
}
