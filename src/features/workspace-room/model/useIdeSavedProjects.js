import { useCallback, useEffect, useRef, useState } from 'react';
import { getIdeCheckpointCapabilities, listIdeCheckpoints, getIdeCheckpoint, discardIdeCheckpoint, abandonIdeCheckpoint, saveIdeCheckpoint, reconcileIdeCheckpoint, restoreIdeCheckpoint, reconcileIdeRestore } from '@api/ide';
import { useAppToast } from '@shared/hooks/useAppToast';
import { checkpointHistory, checkpointResult, restoreResult, savedProjectIntent } from './ideCheckpointContracts';
import { getWorkspaceActorSession } from './workspaceSession';
import { uploadIntentId } from './useWorkUploadSelection';

const initial = scope => ({ scope, available: false, loading: false, history: null, error: '', busy: '', intent: null, inspected: null, outcome: '' });
const notices = {
  ide_checkpoint_quota_exceeded: 'Недостаточно места для снимка проекта. Предыдущие версии сохранены.',
  ide_checkpoint_head_changed: 'История изменилась в другом окне. Обновите список перед сохранением.',
  ide_checkpoint_runtime_not_ready: 'Среда изменилась или завершена. Обновите IDE; сохранённые версии доступны в истории.',
  ide_checkpoint_pending: 'Есть загрузки с неподтверждённым завершением. Проверьте их состояние в истории.',
  ide_checkpoint_restore_pending: 'Восстановление ещё не подтверждено. Проверьте результат, не создавая другую среду.',
  ide_checkpoint_invalid: 'Проект не подходит для снимка: проверьте размер и поддерживаемые файлы.',
  ide_checkpoint_capture_unavailable: 'Не удалось получить снимок из среды. Проверьте результат запроса перед повтором.',
  ide_checkpoint_storage_unavailable: 'Снимок пока не удалось прочитать. Проверьте результат позже.',
  ide_checkpoint_not_discardable: 'Удаление пока недоступно. Обновите состояние снимка; файлы проекта не изменены.',
  ide_checkpoint_not_abandonable: 'Эту попытку уже нельзя отменить. Проверьте состояние снимка; файлы проекта не изменены.',
};
const notice = error => Object.hasOwn(notices, error?.code) ? notices[error.code]
  : 'Результат не подтверждён. Проверьте сохранение в истории; новый запрос автоматически не отправляется.';
const keyFor = scope => `gpthub.ide.pending:${scope}`;
function readIntent(scope) {
  try { return savedProjectIntent(JSON.parse(sessionStorage.getItem(keyFor(scope)))); } catch { return null; }
}
function persist(scope, intent) {
  try { if (intent) sessionStorage.setItem(keyFor(scope), JSON.stringify(intent)); else sessionStorage.removeItem(keyFor(scope)); } catch { /* memory owner remains */ }
}

/** One request owner per visit; reads never replay a mutation or adopt a runtime. */
export function useIdeSavedProjects({ threadId, repositoryId, active, generation, blocked, onRestored }) {
  const scope = `${threadId || ''}:${repositoryId || ''}`;
  const [state, setState] = useState(() => initial(scope));
  const [open, setOpen] = useState(false);
  const [session] = useState(getWorkspaceActorSession);
  const toast = useAppToast();
  const current = useRef({}); current.current = { scope, active, generation, blocked, onRestored, state, open };
  const request = useRef(null);
  const visit = useRef({ scope, active, id: 0 });
  if (visit.current.scope !== scope || visit.current.active !== active) visit.current = { scope, active, id: visit.current.id + 1 };
  const visitId = visit.current.id;
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; request.current?.abort(); }; }, []);
  const start = useCallback(() => {
    if (!mounted.current || visit.current.id !== visitId || !current.current.active || current.current.scope !== scope || !repositoryId || request.current) return null;
    const controller = new AbortController(); request.current = controller;
    return { signal: controller.signal,
      owns: () => mounted.current && visit.current.id === visitId && current.current.active && current.current.scope === scope && request.current === controller && !controller.signal.aborted,
      finish: () => { if (request.current === controller) request.current = null; } };
  }, [scope, repositoryId, visitId]);
  const load = useCallback(async () => {
    const ticket = start(); if (!ticket) return;
    setState(old => ({ ...(old.scope === scope ? old : initial(scope)), loading: true, error: '' }));
    try {
      const capability = await getIdeCheckpointCapabilities(threadId, repositoryId, ticket.signal);
      if (!ticket.owns()) return;
      if (typeof capability?.enabled !== 'boolean') throw Error();
      if (!capability.enabled) { setState(initial(scope)); return; }
      setState(old => ({ ...old, available: true }));
      const history = checkpointHistory(await listIdeCheckpoints(threadId, repositoryId, ticket.signal), repositoryId);
      if (ticket.owns()) setState(old => ({ ...old, history, loading: false, error: '' }));
    } catch {
      if (ticket.owns()) setState(old => ({ ...old, loading: false, error: 'Не удалось загрузить историю. Сохранённые проекты не изменены.' }));
    } finally { ticket.finish(); }
  }, [scope, start, threadId, repositoryId]);
  useEffect(() => {
    request.current?.abort(); request.current = null; setOpen(false);
    setState({ ...initial(scope), intent: readIntent(scope) });
    if (active && repositoryId) void load();
    return () => { request.current?.abort(); request.current = null; };
  }, [scope, active, repositoryId, load]);
  const run = async (kind, item) => {
    const snapshot = current.current;
    if (snapshot.scope !== scope || snapshot.blocked || snapshot.state.scope !== scope || !snapshot.state.available || !snapshot.state.history || snapshot.state.loading) return false;
    const ticket = start(); if (!ticket) return false;
    let intent = snapshot.state.intent;
    if (kind === 'save' && intent) { ticket.finish(); setOpen(true); return false; }
    const history = snapshot.state.history;
    if (kind === 'save') intent = { kind: 'save', checkpoint_id: uploadIntentId(), base_checkpoint_id: history.items.find(row => row.is_current)?.checkpoint_id || null, generation: snapshot.generation };
    if (kind === 'restore') {
      if (intent || history.runtime.state !== 'expired' || !history.runtime.generation || item?.state !== 'published') { ticket.finish(); return false; }
      intent = { kind: 'restore', checkpoint_id: item.checkpoint_id, restore_id: uploadIntentId(), base_generation: history.runtime.generation };
    }
    if (kind === 'check-save' && intent && item && intent.checkpoint_id !== item.checkpoint_id) { ticket.finish(); return false; }
    if (!intent && kind === 'check-save' && ['pending', 'retired', 'conflict'].includes(item?.state)) intent = { kind: 'save', checkpoint_id: item.checkpoint_id };
    if (!intent && kind === 'check-restore' && history.last_restore) intent = { kind: 'restore', ...history.last_restore };
    if (!intent || (kind === 'save' && (!snapshot.generation || history.runtime.state !== 'ready'))) { ticket.finish(); return false; }
    if (kind === 'save' || kind === 'restore') persist(scope, intent);
    setState(old => ({ ...old, busy: kind, error: '', outcome: '', intent }));
    let acknowledged = false;
    try {
      let result;
      if (kind === 'save' || (kind === 'retry' && intent.kind === 'save' && savedProjectIntent(intent))) {
        const { kind: _kind, ...data } = intent;
        result = checkpointResult(await saveIdeCheckpoint(threadId, repositoryId, data, ticket.signal, session), repositoryId, intent.checkpoint_id);
      } else if (kind === 'restore' || (kind === 'retry' && intent.kind === 'restore' && savedProjectIntent(intent))) {
        const { kind: _kind, ...data } = intent;
        result = restoreResult(await restoreIdeCheckpoint(threadId, repositoryId, data, ticket.signal), repositoryId);
      } else if (intent.kind === 'save') {
        result = checkpointResult(await getIdeCheckpoint(threadId, repositoryId, intent.checkpoint_id, ticket.signal), repositoryId, intent.checkpoint_id);
        if (!ticket.owns()) return false;
        setState(old => ({ ...old, inspected: result }));
        if (result.state === 'pending') result = checkpointResult(await reconcileIdeCheckpoint(threadId, repositoryId, intent.checkpoint_id, ticket.signal), repositoryId, intent.checkpoint_id);
      }
      else result = restoreResult(await reconcileIdeRestore(threadId, repositoryId, intent.restore_id, ticket.signal), repositoryId);
      if (!ticket.owns()) return false;
      const restored = intent.kind === 'restore' && result.active;
      const saved = intent.kind === 'save' && result.state === 'published';
      const terminal = saved || restored || ['retired', 'conflict', 'rejected', 'failed'].includes(result.state)
        || (intent.kind === 'restore' && ['published', 'expired'].includes(result.state));
      if (terminal) persist(scope, null);
      acknowledged = terminal;
      const outcome = result.collected ? 'Незавершённый снимок удалён. Файлы проекта не изменены.'
        : saved ? result.is_current ? 'Проект сохранён.' : 'Снимок сохранён в истории. Текущая версия проекта не заменена.'
        : restored ? 'Проект восстановлен.' : result.state === 'published' ? 'Это восстановление уже завершено, но его среда больше не активна.'
          : terminal ? 'Операция завершена без замены текущего проекта.' : 'Результат ещё не подтверждён. Проверьте его в истории.';
      setState(old => ({ ...old, intent: terminal ? null : intent, outcome,
        ...(intent.kind === 'save' ? { inspected: result } : {}) }));
      if (restored) current.current.onRestored?.();
      if (saved || restored) {
        if (!current.current.open) toast({ title: outcome, status: 'success', operationId: intent.checkpoint_id });
      } else setOpen(true);
      const next = checkpointHistory(await listIdeCheckpoints(threadId, repositoryId, ticket.signal), repositoryId);
      if (ticket.owns()) setState(old => ({ ...old, history: next }));
      return Boolean(saved || restored || result.collected);
    } catch (error) {
      if (ticket.owns()) {
        // These closed admission failures guarantee no row/upload was reserved.
        const refused = kind === 'save' && ['ide_checkpoint_quota_exceeded', 'ide_checkpoint_head_changed', 'ide_checkpoint_pending'].includes(error?.code);
        if (refused) persist(scope, null);
        setState(old => ({ ...old, ...(refused ? { intent: null } : {}),
          error: acknowledged ? 'Результат операции подтверждён, но список версий не обновился. Обновите историю.' : notice(error) }));
        setOpen(true);
      }
      return false;
    } finally {
      if (ticket.owns()) setState(old => ({ ...old, busy: '' }));
      ticket.finish();
    }
  };
  const retire = async (item, operation) => {
    const revoking = operation === 'abandon';
    const snapshot = current.current;
    const checkpointId = item?.checkpoint_id;
    const known = snapshot.state.history?.items.find(row => row.checkpoint_id === checkpointId)
      || (snapshot.state.intent?.kind === 'save' && snapshot.state.intent.checkpoint_id === checkpointId ? snapshot.state.inspected : null);
    if (snapshot.scope !== scope || snapshot.blocked || snapshot.state.loading || !snapshot.state.available
      || !known || known.state === 'published' || !(revoking ? item.can_abandon : item.can_discard)) return false;
    const ticket = start(); if (!ticket) return false;
    setState(old => ({ ...old, busy: operation, error: '', outcome: '' }));
    let acknowledged = false;
    const accept = result => {
      const clear = current.current.state.intent?.kind === 'save'
        && current.current.state.intent.checkpoint_id === checkpointId && (result.collected || result.state === 'published'
          || (revoking && ['retired', 'conflict'].includes(result.state)));
      if (clear) persist(scope, null);
      setState(old => ({ ...old, inspected: result, ...(clear ? { intent: null } : {}) }));
    };
    try {
      // Revalidate immediately before destructive dispatch: publication may have won meanwhile.
      let result = checkpointResult(await getIdeCheckpoint(threadId, repositoryId, checkpointId, ticket.signal), repositoryId, checkpointId);
      if (!ticket.owns()) return false;
      accept(result);
      if (result.state === 'published' || result.is_current) {
        setState(old => ({ ...old, outcome: `Снимок уже сохранён. ${revoking ? 'Отмена не выполнена' : 'Удаление не выполнено'}.` }));
        return false;
      }
      if (revoking && result.state === 'pending') {
        if (!result.can_abandon) throw Object.assign(new Error(), { code: 'ide_checkpoint_not_abandonable' });
        result = checkpointResult(await abandonIdeCheckpoint(threadId, repositoryId, checkpointId, ticket.signal), repositoryId, checkpointId);
        if (!ticket.owns()) return false;
        accept(result);
      } else if (!revoking && !result.collected) {
        if (!result.can_discard) throw Object.assign(new Error(), { code: 'ide_checkpoint_not_discardable' });
        const response = await discardIdeCheckpoint(threadId, repositoryId, checkpointId, ticket.signal);
        if (typeof response?.cleanup_pending !== 'boolean') throw Error();
        result = checkpointResult(response, repositoryId, checkpointId);
        if (!ticket.owns()) return false;
        accept(result);
      }
      acknowledged = revoking ? ['retired', 'conflict'].includes(result.state) : result.collected;
      setState(old => ({ ...old, outcome: revoking && acknowledged ? 'Попытка отменена. Файлы проекта не изменены.'
        : acknowledged ? 'Незавершённый снимок удалён. Файлы проекта не изменены.'
        : 'Удаление ещё не подтверждено. Место пока не освобождено; можно проверить результат позже.' }));
      const history = checkpointHistory(await listIdeCheckpoints(threadId, repositoryId, ticket.signal), repositoryId);
      if (ticket.owns()) setState(old => ({ ...old, history }));
      return acknowledged;
    } catch (error) {
      if (ticket.owns()) setState(old => ({ ...old, error: acknowledged ? `${revoking ? 'Отмена подтверждена' : 'Удаление подтверждено'}, но история не обновилась. Обновите список.`
        : ['ide_checkpoint_not_discardable', 'ide_checkpoint_not_abandonable'].includes(error?.code) ? notice(error)
          : `${revoking ? 'Отмена не подтверждена' : 'Удаление не подтверждено'}. Проверьте результат в истории перед повтором.` }));
      return false;
    } finally {
      if (ticket.owns()) setState(old => ({ ...old, busy: '' }));
      ticket.finish();
    }
  };
  const visible = state.scope === scope ? state : initial(scope);
  return { ...visible, open: active && open, show: () => { setOpen(true); setState(old => ({ ...old, outcome: '' })); void load(); }, close: () => setOpen(false), load,
    save: () => run('save'), retry: () => run('retry'), restore: item => run('restore', item),
    discard: item => retire(item, 'discard'), abandon: item => retire(item, 'abandon'), check: item => run('check-save', item), checkRestore: () => run('check-restore') };
}
