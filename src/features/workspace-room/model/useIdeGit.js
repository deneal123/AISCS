import { useCallback, useEffect, useRef, useState } from 'react';
import { operateIdeGit } from '@api/ide';
import { getWorkspaceActorSession } from './workspaceSession';

const errors = {
  ide_git_not_empty: 'Клонировать можно только в пустую среду. Создайте отдельный проект для другого репозитория.',
  ide_git_conflict: 'В этой среде уже есть Git-репозиторий. Существующие данные не заменены.',
  ide_git_url_invalid: 'Введите HTTPS-ссылку на публичный репозиторий GitHub, без токена и параметров.',
  ide_git_branch_missing: 'Ветка не найдена. Проверьте название или оставьте поле пустым для основной ветки.',
  ide_git_limit: 'Репозиторий превышает лимит загрузки 20 МБ.',
  ide_git_fetch_failed: 'Не удалось загрузить публичный репозиторий. Проверьте ссылку и доступность GitHub.',
};

export function useIdeGit({ threadId, repositoryId, generation, active, onChanged, onCloneConflict }) {
  const scope = `${threadId}:${repositoryId}:${generation}`;
  const [session] = useState(getWorkspaceActorSession);
  const [state, setState] = useState({ scope, data: null, busy: '', error: '', outcome: '' });
  const current = useRef({}); current.current = { scope, active, onChanged, onCloneConflict };
  const pending = useRef(null);
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; pending.current?.abort(); }; }, []);
  const run = useCallback(async (operation = 'status', values = {}) => {
    if (!mounted.current || current.current.scope !== scope || !current.current.active || !generation || pending.current) return false;
    const controller = new AbortController(); pending.current = controller;
    const valid = () => mounted.current && current.current.active && current.current.scope === scope && pending.current === controller && !controller.signal.aborted;
    setState(old => ({ ...(old.scope === scope ? old : { data: null }), scope, busy: operation, error: '', outcome: operation === 'status' && old.scope === scope ? old.outcome : '' }));
    try {
      const data = await operateIdeGit(threadId, repositoryId, { operation, generation, ...values }, controller.signal, session);
      if (!valid()) return false;
      if (data.repository_id !== repositoryId || data.generation !== generation || typeof data.initialized !== 'boolean'
        || !(data.branch === null || (typeof data.branch === 'string' && data.branch.length <= 200))) throw Error();
      setState(old => ({ scope, data, busy: '', error: '', outcome: operation === 'clone' ? 'Репозиторий клонирован с историей выбранной ветки.' : operation === 'init' ? 'Git инициализирован. Коммит ещё не создан.' : old.scope === scope ? old.outcome : '' }));
      if (operation !== 'status') current.current.onChanged?.();
      return true;
    } catch (error) {
      if (valid() && operation === 'clone' && ['ide_git_not_empty', 'ide_git_conflict'].includes(error?.code) && current.current.onCloneConflict) {
        const completed = await current.current.onCloneConflict(values);
        if (valid()) setState(old => ({ ...old, busy: '', error: '' }));
        return completed;
      }
      if (valid()) setState(old => ({ ...old, busy: '', error: operation === 'status' ? 'Не удалось прочитать состояние Git.'
        : Object.hasOwn(errors, error?.code) ? errors[error.code] : 'Результат операции не подтверждён. Обновите состояние Git перед повтором.' }));
      return false;
    } finally { if (pending.current === controller) pending.current = null; }
  }, [scope, generation, threadId, repositoryId, session]);
  useEffect(() => {
    pending.current?.abort(); pending.current = null;
    setState(old => old.scope === scope ? { ...old, busy: '' } : { scope, data: null, busy: '', error: '', outcome: '' });
    if (active && generation) void run('status');
    return () => { pending.current?.abort(); pending.current = null; };
  }, [scope, active, generation, run]);
  return { ...(state.scope === scope ? state : { data: null, busy: '', error: '', outcome: '' }), run };
}
