const STAGE_LABELS = Object.freeze({
  intent: 'Подготовка задания',
  evidence: 'Материалы и источники',
  outline: 'Структура документа',
  section_authoring: 'Написание разделов',
  source_publish: 'Сохранение исходников',
  compile: 'Сборка PDF',
  deterministic_audit: 'Техническая проверка',
  visual_audit: 'Визуальная проверка',
  delivery: 'Сохранение в Библиотеку',
});

const STATUS_LABELS = Object.freeze({
  running: 'выполняется',
  ready: 'готово',
  empty: 'нет данных',
  pending: 'ожидает продолжения',
  queued: 'поставлено в очередь',
  draft_ready: 'черновик готов',
  completed: 'завершено',
  deferred: 'отложено',
  failed: 'не выполнено',
});

const FAILURE_LABELS = Object.freeze({
  draft_protocol: 'Модель не вернула структуру документа в ожидаемом формате.',
  draft_invalid: 'Полученная структура документа не прошла проверку.',
  evidence_incomplete: 'Для финальной статьи недостаточно проверяемых источников.',
  source_conflict: 'Исходники изменились; более свежие правки не перезаписаны.',
  compile_failed: 'LaTeX-сборка завершилась ошибкой.',
  deterministic_audit_failed: 'PDF не прошёл техническую проверку.',
  visual_pending: 'Визуальная проверка временно недоступна.',
  visual_audit_failed: 'PDF не прошёл визуальную проверку.',
  delivery_deferred: 'Файл будет сохранён в Библиотеку после восстановления сервиса.',
  selected_model_unavailable: 'Выбранная модель недоступна; подмена не выполнялась.',
  workspace_unavailable: 'Рабочее место временно недоступно.',
  authoring_unsupported: 'Запрошенная структура пока не поддерживается автоматически.',
  unresolved_requirements: 'Не заполнены обязательные реквизиты документа.',
  cancelled: 'Подготовка документа отменена.',
  internal: 'Подготовку документа не удалось завершить.',
});

export function presentDocumentStatus(value) {
  const stage = STAGE_LABELS[value?.stage] || 'Подготовка документа';
  const status = STATUS_LABELS[value?.status] || 'состояние обновлено';
  const failure = FAILURE_LABELS[value?.failure_code] || '';
  const failed = value?.status === 'failed' || value?.outcome === 'failed';
  return {
    kind: failed ? 'error' : ['ready', 'completed'].includes(value?.status) ? 'done' : 'info',
    title: `${stage}: ${status}`,
    detail: failure || (value?.retryable ? 'Можно безопасно повторить действие.' : ''),
  };
}

export default presentDocumentStatus;
