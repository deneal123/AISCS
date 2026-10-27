const VIDEO_STAGE_LABELS = Object.freeze({
  probe: 'Проверяю доступность и длительность видео',
  proxy_retry: 'Повторяю обращение через прокси',
  download: 'Загружаю видео',
  frames: 'Подготавливаю кадры видео',
  transcript: 'Получаю субтитры и расшифровку',
  source_ready: 'Расшифровка получена',
  authoring: 'Готовлю конспект',
  workspace_save: 'Сохраняю конспект в Рабочем месте',
  library_delivery: 'Готовлю файл для скачивания из Библиотеки',
});

export function isYoutubeSource(value) {
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase();
    return ['http:', 'https:'].includes(url.protocol)
      && (host === 'youtu.be' || host === 'youtube.com' || host.endsWith('.youtube.com'));
  } catch {
    return false;
  }
}

export function presentVideoProgress(value) {
  if (!value || !Object.hasOwn(VIDEO_STAGE_LABELS, value.stage)) return null;
  const current = Number.isInteger(value.current) && value.current > 0 ? value.current : null;
  const total = Number.isInteger(value.total) && value.total > 0 && value.total <= 100000 ? value.total : null;
  const parts = value.stage === 'authoring' && current && total && current <= total
    ? ` · часть ${current} из ${total}` : '';
  return {
    label: VIDEO_STAGE_LABELS[value.stage] + parts,
    stage: value.stage,
    heartbeat: value.heartbeat === true,
  };
}
