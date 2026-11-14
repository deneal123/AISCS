// The physical recording covers the reconstructed source population, not all
// graph nodes. Older recordings may not include an explicit cell count.
export function fieldRecordingScope(run) {
  const count = run?.result?.preview?.source_cells;
  return Number.isSafeInteger(count) && count > 0
    ? `E1 − REF · клеток: ${count.toLocaleString('ru-RU')}`
    : 'E1 − REF · выбранные клетки';
}

export function fieldResultHeading(run, direct) {
  return direct ? 'Модельная активность ЦНС' : fieldRecordingScope(run);
}

export function fieldResultDescription(run, direct) {
  if (run?.result?.manifest?.kind === 'experimental-full-population-feedback') {
    return 'Модельная запись всех клеток · без артефакта стимуляции';
  }
  return direct
    ? 'Упрощённая сеть · запись E1–REF не рассчитана'
    : `${run?.title || 'STIM'} · запись выбранных клеток, без артефакта`;
}

export function fieldProxyExplanation(direct) {
  const base = 'На сцене показаны события упрощённой модели всей сети, включая фоновую активность.';
  return direct
    ? `${base} Запись E1–REF в этом режиме не рассчитывается. Коэффициент сетевого ответа не откалиброван.`
    : `${base} Запись E1–REF рассчитана отдельно для выбранных клеток; модели не образуют единую биофизическую систему. Коэффициент сетевого ответа не откалиброван.`;
}

// Only use this with the histogram verified against the network event file.
export function fieldProxyActivityNotice(run, histogram) {
  const preview = run?.result?.preview, gain = run?.configuration?.gain;
  const neurons = preview?.neurons, active = preview?.active_neurons;
  if (!Array.isArray(histogram) || !histogram.length
      || !histogram.every(value => Number.isSafeInteger(value) && value >= 0)
      || !Number.isSafeInteger(neurons) || neurons <= 0
      || !Number.isSafeInteger(active) || active < 0 || active > neurons
      || !Number.isFinite(gain)) return null;
  const peak = Math.max(...histogram);
  if (peak > neurons) return null;
  return `Некалиброванный коэффициент связи поля с сетью: ${gain.toLocaleString('ru-RU')}. `
    + `Модельные события за расчёт: ${active.toLocaleString('ru-RU')} из ${neurons.toLocaleString('ru-RU')} клеток; `
    + `максимум за 1 мс — ${peak.toLocaleString('ru-RU')}. Это не измеренная физиологическая активность.`;
}

export function fieldExclusionNotice(preview) {
  const missing = preview?.direct_field_exclusions, contacts = preview?.contact_exclusions;
  if (!Number.isSafeInteger(missing) || missing < 0 || !Number.isSafeInteger(contacts) || contacts < 0
      || missing + contacts === 0) return null;
  return `Прямое действие поля не рассчитано для ${missing + contacts} клеток: `
    + `нет кривизны — ${missing}, пересечение контакта — ${contacts}. Их сетевой ответ может сохраняться.`;
}

export function directFieldTimeline(run) {
  const duration = run?.result?.preview?.duration_ms;
  const waveform = run?.configuration?.waveform;
  if (!Number.isInteger(duration) || duration < 1 || duration > 1000
      || !Array.isArray(waveform) || waveform.length !== duration
      || !waveform.every(Number.isFinite)) return null;
  return {
    time_ms: Array.from({ length: duration + 1 }, (_, i) => i),
    stimulus_fraction: waveform,
    stimulus_time_ms: waveform.map((_, i) => i + 0.5),
  };
}

// A network-only result must refer to the same scene and stimulus snapshot.
export function directFieldMatchesScene(field, simulation, sceneId, graphManifest) {
  if (!field || !simulation || typeof simulation !== 'object' || Array.isArray(simulation)
      || typeof sceneId !== 'string' || !sceneId || typeof graphManifest !== 'string' || !graphManifest) return false;
  if (!['source_um', 'return_um'].every(key => Array.isArray(simulation[key])
      && simulation[key].length === 3 && simulation[key].every(Number.isFinite))
      || !Number.isFinite(simulation.current_na) || !Number.isFinite(simulation.conductivity_s_m)
      || simulation.conductivity_s_m <= 0 || !Number.isFinite(simulation.clearance_um)
      || simulation.clearance_um <= 0 || typeof simulation.coordinate_frame !== 'string'
      || !simulation.coordinate_frame) return false;
  const result = field.result?.preview;
  const keys = ['source_um', 'return_um', 'current_na', 'conductivity_s_m', 'clearance_um', 'coordinate_frame'];
  return field.state === 'completed' && field.parent_run_id === sceneId
    && field.result?.manifest?.kind === 'experimental-field-proxy' && result?.recording === null
    && field.configuration?.graph_manifest_sha256 === graphManifest
    && Number.isInteger(simulation.duration_ms) && result.duration_ms === simulation.duration_ms
    && keys.every(key => simulation[key] !== undefined
      && JSON.stringify(field.configuration?.[key]) === JSON.stringify(simulation[key]));
}

// Surface normals describe the draft's positions and must not leak to another placement.
export function contactNormalsForSimulation(draft, simulation) {
  const keys = ['source_um', 'return_um', 'electrode_um', 'reference_um'];
  if (!draft?.simulation || !simulation || keys.some(key => !Array.isArray(simulation[key])
      || simulation[key].length !== 3 || !simulation[key].every(Number.isFinite)
      || JSON.stringify(draft.simulation[key]) !== JSON.stringify(simulation[key]))) return null;
  return draft.normals || null;
}
