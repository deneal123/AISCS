export function executorStartError(code) {
  if (code === 'executor_field_contact_exclusion') return 'STIM пересекает реконструкцию отростка. Измените положение контактов.';
  if (code === 'executor_field_source_missing') return 'Не найдена реконструкция клетки; полный расчёт остановлен.';
  if (code === 'executor_field_invalid_geometry') return 'Обнаружена некорректная геометрия клетки; расчёт остановлен.';
  if (code === 'executor_field_partial_geometry') return 'Обнаружена неполная геометрия клетки; расчёт остановлен.';
  if (code === 'executor_field_missing_curvature') return 'Для одной из клеток невозможно вычислить показатель поля.';
  if (code === 'executor_endpoint_missing') return 'Исполнитель не поддерживает этот режим. Обновите сервис генератора.';
  if (code === 'executor_contract_rejected') return 'Исполнитель отклонил параметры. Проверьте совместимость версий сервисов.';
  if (code === 'executor_attempt_identity') return 'Найден несовместимый запуск с тем же идентификатором. Результат не изменён.';
  return '';
}
