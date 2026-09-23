const REASON_LABELS = {
  shortcut_empty: 'Пустой запрос обработан обычным режимом.',
  shortcut_smalltalk: 'Короткое сообщение обработано без вызова модели.',
  shortcut_continue: 'Продолжение прошлого ответа обработано без вызова модели.',
  model_classification: 'Режим определён по типу задачи.',
  confirmation_required: 'Дорогой режим ждёт подтверждения.',
  video_confirmation_required: 'Просмотр видео ждёт подтверждения.',
  disabled: 'Автоматический выбор режима сейчас отключён.',
  explicit_route: 'Использован выбранный режим.',
  explicit_search: 'Использован выбранный режим поиска.',
  nontext_input: 'Для этого типа вложения используется отдельный маршрут.',
  multimodal_input: 'Для нескольких вложений используется отдельный маршрут.',
  pre_resolved_route: 'Маршрут был определён до запуска авто-режима.',
  decision_unavailable: 'Автоматический выбор режима временно недоступен.',
};

export function autoModeReasonLabel(reasonCode) {
  return REASON_LABELS[reasonCode] || 'Решение принято по правилам авто-режима.';
}
