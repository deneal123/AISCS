export const EMPTY_WORK_HUB = {
  contract_version: 2,
  loading: false,
  refreshing: false,
  workspace: {
    state: 'absent', entries: [], history: [], revision: '', recovered: false, truncated: false,
  },
  room: {
    state: 'absent', issues: [], issue_count: 0, leases: [], activity: [], control: { state: 'running' },
  },
  library: { state: 'ready', items: [], next_cursor: null, next_offset: null },
  history: [],
};

export const ACTIVITY_LABELS = {
  lease_acquired: 'Файл открыт для правки',
  lease_released: 'Правка файла завершена',
  file_saved: 'Файл сохранён',
  library_copied: 'Файл добавлен из библиотеки',
  issue_created: 'Добавлена задача',
  issue_updated: 'Задача обновлена',
  issue_resolved: 'Задача отмечена выполненной',
  issue_stale: 'Задача требует проверки',
  agent_started: 'Агент начал работу',
  agent_waiting: 'Агент ожидает безопасной паузы',
  agent_paused: 'Агент на паузе',
  agent_resumed: 'Агент продолжил работу',
  agent_cancelled: 'Запуск агента отменён',
  workspace_recovered: 'Рабочее место восстановлено',
};

export const ISSUE_STATUS_LABELS = {
  open: 'Открыта',
  resolved: 'Решена',
  stale: 'Требует проверки',
};

export const HISTORY_TYPE_LABELS = {
  agent_run: 'Изменения агента',
  import: 'Импорт файла',
  user_edit: 'Правка пользователя',
  revert: 'Откат рабочего места',
  document_scaffold: 'Создание документа',
  document_authoring: 'Правка документа',
  document_profile: 'Формат документа',
};

export const LEASE_REASON_LABELS = {
  occupied: 'Файл уже редактируется в другом окне.',
  expired: 'Срок права на редактирование истёк.',
  unavailable: 'Право на редактирование временно недоступно.',
  navigation: 'Редактирование завершено при переходе.',
};

export const workspaceStatusText = {
  unselected: 'Выберите существующий чат: библиотека доступна и без временной рабочей среды.',
  absent: 'Среда появится, когда агенту понадобится работать с файлами.',
  expired: 'Срок рабочей среды истёк. Следующий запуск создаст новую среду.',
  unavailable: 'Рабочее место временно недоступно. Данные не изменялись.',
};
