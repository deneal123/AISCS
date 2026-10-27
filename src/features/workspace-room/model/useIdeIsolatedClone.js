import { useEffect, useRef, useState } from 'react';
import { cloneIdeRepository, getIdeClone } from '@api/ide';
import { ideCloneRecovery, ideRepositoryPage } from './ideReadContracts';
import { getWorkspaceActorSession } from './workspaceSession';
import { uploadIntentId } from './useWorkUploadSelection';

const states = new Set(['preparing', 'running', 'blocked', 'complete', 'failed', 'unconfirmed']);
export const IDE_CLONE_NOTICES = {
  complete: 'Клонирование завершено.',
  preparing: 'Отдельная среда ещё запускается. Продолжите ту же попытку после её готовности.',
  running: 'Клонирование выполняется в отдельном проекте. Проверьте результат; повторная запись не запускается.',
  blocked: 'Отдельная среда пока недоступна. Откройте созданный проект, чтобы проверить её состояние.',
  failed: 'Клонирование не завершено. Исходный проект сохранён; созданный проект доступен для просмотра.',
  unconfirmed: 'Результат клонирования не подтверждён. Проверьте созданный проект; Git-запись автоматически не повторяется.',
};
const notices = IDE_CLONE_NOTICES;

function result(value, sourceId) {
  const repository = ideRepositoryPage({ items: [value?.repository], next_offset: null }, 0).items[0];
  if (!states.has(value.state) || repository.repository_id === sourceId) throw Error('ide_invalid_clone');
  return { repository: { ...repository, state: 'registered' }, state: value.state };
}

/** Lost ACKs reconcile the same durable intent; a read failure never creates another. */
export function useIdeIsolatedClone({ threadId, repositoryId, active, onCloned, onRecorded }) {
  const scope = `${threadId}:${repositoryId}`;
  const [session] = useState(getWorkspaceActorSession);
  const [state, setState] = useState({ scope, busy: false, error: '', result: null });
  const intent = useRef(null);
  const pending = useRef(null);
  const alive = useRef(false);
  const current = useRef({}); current.current = { scope, active, onCloned, onRecorded };
  useEffect(() => { alive.current = true; return () => { alive.current = false; pending.current?.abort(); }; }, []);
  useEffect(() => {
    pending.current?.abort(); pending.current = null;
    if (intent.current?.scope !== scope) intent.current = null;
    setState(old => old.scope === scope ? { ...old, busy: false } : { scope, busy: false, error: '', result: null });
    return () => { pending.current?.abort(); pending.current = null; };
  }, [scope, active]);
  const run = async (values) => {
    if (!alive.current || !current.current.active || current.current.scope !== scope || pending.current) return false;
    if (!intent.current && !values?.origin) return false;
    if (!intent.current) intent.current = { scope, sent: false, data: { intent_id: uploadIntentId(), source_repository_id: repositoryId, ...values } };
    const request = intent.current;
    const parse = value => {
      const response = result(value, request.data.source_repository_id);
      if (request.repositoryId && request.repositoryId !== response.repository.repository_id) throw Error('ide_invalid_clone');
      request.repositoryId = response.repository.repository_id;
      return response;
    };
    const controller = new AbortController(); pending.current = controller;
    const valid = () => alive.current && current.current.active && current.current.scope === scope && pending.current === controller && !controller.signal.aborted;
    setState(old => ({ ...old, scope, busy: true, error: '' }));
    try {
      let response;
      if (request.sent) {
        try { response = parse(await getIdeClone(threadId, request.data.intent_id, controller.signal)); }
        catch (error) { if (error?.status !== 404) throw error; }
      }
      if (!valid()) return false;
      if (!response || ['preparing', 'blocked'].includes(response.state)) {
        request.sent = true;
        try { response = parse(await cloneIdeRepository(threadId, request.data, controller.signal, session)); }
        catch (error) {
          if (!valid()) return false;
          // One read can recover an acknowledged journal result, but never POSTs.
          response = parse(await getIdeClone(threadId, request.data.intent_id, controller.signal));
        }
      }
      if (!valid()) return false;
      setState({ scope, busy: false, result: response, error: notices[response.state] || '' });
      current.current.onRecorded?.();
      if (response.state === 'complete') { current.current.onCloned?.(response.repository); return true; }
    } catch {
      if (valid()) setState(old => ({ ...old, scope, busy: false, error: 'Не удалось проверить попытку клонирования. Повторите проверку; новый проект автоматически не создаётся.' }));
    } finally { if (pending.current === controller) pending.current = null; }
    return false;
  };
  const visible = state.scope === scope ? state : { busy: false, error: '', result: null };
  return { ...visible, locked: intent.current?.scope === scope, request: intent.current?.scope === scope ? intent.current.data : null, run,
    restore: attempt => {
      if (!alive.current || !current.current.active || current.current.scope !== scope || pending.current || !attempt?.request) return false;
      try { attempt = ideCloneRecovery({ attempt }, repositoryId); } catch { return false; }
      intent.current = { scope, sent: true, repositoryId: attempt.repository.repository_id,
        data: { intent_id: attempt.intent_id, source_repository_id: attempt.source_repository_id, ...attempt.request } };
      setState({ scope, busy: false, error: notices[attempt.state] || '', result: attempt });
      return true;
    },
    fresh: () => {
      if (!alive.current || !current.current.active || current.current.scope !== scope || pending.current) return false;
      intent.current = null; setState({ scope, busy: false, error: '', result: null }); return true;
    },
    open: () => { if (alive.current && current.current.active && current.current.scope === scope && visible.result && !visible.busy) current.current.onCloned?.(visible.result.repository); } };
}
