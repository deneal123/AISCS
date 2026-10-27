import manifest from './protocolManifest.json';

const BLOCKERS = Object.freeze({
  cancelled: 'Задание остановлено. Новые действия не запускаются.',
  cost_unknown: 'Расход ещё не подтверждён. Повторный запуск автоматически не выполняется.',
  operation_unknown: 'Результат операции не подтверждён. Повторное исполнение заблокировано.',
  unconfirmed_effect: 'Изменение не подтверждено. Сначала требуется сверить состояние операции.',
  verification_missing: 'Не хватает подтверждений обязательных проверок.',
  verification_failed: 'Обязательная проверка не пройдена. Завершение задачи не подтверждено.',
  verification_unavailable: 'Обязательная проверка недоступна. Завершение задачи не подтверждено.',
  plan_incomplete: 'Не все обязательные шаги завершены.',
  budget_exhausted: 'Лимит задания исчерпан. Автоматического увеличения бюджета нет.',
  budget_unavailable: 'Не удалось подтвердить резерв бюджета. Новые платные действия не начаты.',
  checkpoint_unavailable: 'Состояние задания не подтверждено. Новые действия приостановлены.',
  checkpoint_conflict: 'Сохранённое состояние изменилось. Продолжение требует сверки.',
  provider_state_incompatible: 'Продолжение с выбранной моделью несовместимо. Подмена не выполнялась.',
  binding_changed: 'Проект или его версия изменились. Продолжение по прежней версии запрещено.',
  user_decision_required: 'Для продолжения нужен ваш ответ.',
  task_contract_invalid: 'Не удалось согласовать проверяемые критерии задачи. Работа не подтверждена.',
  task_permission_denied: 'Нужное действие не разрешено для этого задания.',
  dispatch_disabled: 'Новые действия этого режима временно отключены.',
  harness_fenced: 'Попытка больше не владеет заданием. Новые действия запрещены.',
  unsupported_adapter: 'Инструмент не поддерживает подтверждаемое исполнение.',
  usage_limit_exceeded: 'Достигнут предел расхода задания. Новые платные действия не начаты.',
  operation_conflict: 'Сохранённая операция отличается от запроса. Повторное исполнение запрещено.',
  no_progress: 'Повторяющиеся действия не дали прогресса. Работа остановлена.',
  prompt_budget: 'Достигнут лимит рабочего контекста задания.',
  round_limit: 'Достигнут предел шагов задания. Завершение не подтверждено.',
  tool_failed: 'Не все обязательные действия инструмента выполнены.',
});

const UNKNOWN = Object.freeze({
  status: 'blocked', kind: 'info', title: 'Результат задачи не подтверждён',
  detail: 'Не удалось распознать подтверждённый итог. Автоматический повтор не выполняется.',
});

const TITLES = Object.freeze({
  completed: 'Задача выполнена и проверена',
  partial: 'Задача выполнена частично',
  blocked: 'Задача заблокирована',
  waiting_user: 'Нужен ваш ответ',
  cancelled: 'Задание остановлено',
});

/** Только безопасная проекция серверного результата; не полномочия и не новый запуск. */
export function presentTaskResult(value) {
  if (value == null) return null; // Старые сообщения без harness сохраняют прежнее представление.
  if (typeof value !== 'object' || Array.isArray(value)) return UNKNOWN;
  const v2 = value.schema_version === 2;
  const contract = v2 ? manifest.task_result.v2 : manifest.task_result;
  if (![1, 2].includes(value.schema_version) || !contract.statuses.includes(value.status)
    || typeof value.verified !== 'boolean') return UNKNOWN;
  const completed = v2 && value.status === 'completed';
  if (completed && (!value.verified || !Array.isArray(value.confirmed) || !value.confirmed.length
    || !Array.isArray(value.unchecked) || value.unchecked.length
    || !Array.isArray(value.references) || !value.references.length
    || value.blocker != null)) return UNKNOWN;
  if (!completed && value.verified !== false) return UNKNOWN;
  const blocker = contract.blockers.includes(value.blocker) ? value.blocker : '';
  const detail = completed ? 'Все обязательные критерии подтверждены исполнителями.'
    : Object.hasOwn(BLOCKERS, blocker) ? BLOCKERS[blocker]
      : 'Обязательные результаты пока не подтверждены.';
  return {
    status: value.status, kind: completed ? 'done' : 'info',
    title: TITLES[value.status], detail,
  };
}
