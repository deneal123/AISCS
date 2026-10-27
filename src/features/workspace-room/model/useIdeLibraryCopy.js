import { useCallback, useEffect, useRef, useState } from 'react';
import { copyLibraryToIde, leaseIdeFile } from '@api/ide';
import { ideLibraryReceipt, idePath } from './ideReadContracts';
import { getWorkspaceActorSession } from './workspaceSession';

const empty = scope => ({ scope, file: null, path: '', busy: false, error: '', invalid: false, done: false, uncertain: false, outcomes: {} });
const errors = {
  ide_file_changed: 'Этот путь уже занят. Выберите другое имя; существующий файл не изменён.',
  ide_file_missing: 'Родительская папка не найдена. Создайте её в IDE или укажите другой путь.',
  ide_path_forbidden: 'Этот путь недоступен. Выберите обычный путь внутри репозитория.',
  ide_library_missing: 'Файл библиотеки недоступен. Обновите библиотеку.',
  ide_library_limit: 'Для копирования в IDE размер файла не должен превышать 20 МиБ.',
  ide_library_integrity: 'Не удалось подтвердить целостность источника. Файл не скопирован.',
  ide_library_unavailable: 'Не удалось прочитать файл библиотеки. Повторите позже.',
  ide_edit_lease_changed: 'Файл занят другим действием. Дождитесь его завершения.',
};

/** One pinned destination; mutations never retry or fall back to Chat/PDF. */
export function useIdeLibraryCopy({ threadId, target, active }) {
  const scope = `${threadId}:${target?.repository_id}:${target?.generation}`;
  const [state, setState] = useState(() => empty(scope));
  const pending = useRef(null);
  const origin = useRef(null);
  const alive = useRef(false);
  const current = useRef({}); current.current = { scope, active, target, state };
  const actorSession = getWorkspaceActorSession();
  useEffect(() => { alive.current = true; return () => { alive.current = false; pending.current?.abort(); }; }, []);
  useEffect(() => {
    pending.current?.abort(); pending.current = null; setState(empty(scope));
    return () => { pending.current?.abort(); pending.current = null; };
  }, [scope, active]);
  const owns = () => alive.current && current.current.scope === scope && current.current.active;
  const eligible = () => owns() && !current.current.target?.blocked && Boolean(target?.generation) && !pending.current;
  const choose = (file, sourceControl) => {
    if (!eligible()) return;
    origin.current = sourceControl;
    const name = String(file.name || '').replaceAll('\\', '/').split('/').at(-1);
    setState(old => ({ ...empty(scope), outcomes: old.scope === scope ? old.outcomes : {}, file: { file_id: file.file_id, name: file.name }, path: idePath(name) ? name : '' }));
  };
  const submit = useCallback(async () => {
    const snapshot = current.current.state;
    if (!eligible() || snapshot.scope !== scope || !snapshot.file || snapshot.done || snapshot.uncertain) return false;
    const path = snapshot.path.trim();
    if (!idePath(path)) { setState(old => ({ ...old, invalid: true })); return false; }
    const controller = new AbortController(); pending.current = controller;
    const valid = () => alive.current && current.current.scope === scope && current.current.active && pending.current === controller && !controller.signal.aborted;
    const refresh = () => {
      try { Promise.resolve(current.current.target?.refresh?.()).catch(() => {}); } catch { /* An independent read cannot revoke a write receipt. */ }
    };
    let fence = 0; let dispatched = false;
    setState(old => ({ ...old, busy: true, invalid: false, error: '' }));
    try {
      const lease = await leaseIdeFile(threadId, target.repository_id, { path, generation: target.generation, action: 'acquire' }, controller.signal, actorSession);
      if (!Number.isSafeInteger(lease?.fence) || lease.fence < 1 || lease.repository_id !== target.repository_id || lease.generation !== target.generation) throw new Error('lease_unconfirmed');
      fence = lease.fence;
      if (!valid() || current.current.target?.blocked) return false;
      dispatched = true;
      const result = await copyLibraryToIde(threadId, target.repository_id, snapshot.file.file_id,
        { path, generation: target.generation, fence }, controller.signal, actorSession);
      ideLibraryReceipt(result, target.repository_id, path, target.generation);
      if (!valid()) return false;
      setState(old => ({ ...old, done: true, path, outcomes: { ...old.outcomes, [snapshot.file.file_id]: 'imported' } }));
      refresh();
      return true;
    } catch (error) {
      if (valid()) {
        const message = typeof error?.code === 'string' && Object.hasOwn(errors, error.code) ? errors[error.code] : null;
        const uncertain = dispatched && !message;
        setState(old => ({ ...old, uncertain,
          error: message || (uncertain ? 'Копирование не подтверждено. Обновите IDE и проверьте путь перед новым действием.' : 'Не удалось получить право записи. Файл не скопирован.') }));
        if (uncertain) refresh();
      }
      return false;
    } finally {
      if (fence) await leaseIdeFile(threadId, target.repository_id, { path, generation: target.generation, action: 'release', fence }, undefined, actorSession).catch(() => {});
      if (pending.current === controller) { pending.current = null; if (alive.current && current.current.scope === scope) setState(old => ({ ...old, busy: false })); }
    }
  // target callbacks may change without retargeting an admitted operation.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, threadId, target?.repository_id, target?.generation, actorSession]);
  const visible = state.scope === scope ? state : empty(scope);
  return { ...visible, choose, submit,
    setPath: path => { if (owns() && !pending.current && !current.current.state.done && !current.current.state.uncertain) setState(old => ({ ...old, path, error: '', invalid: false })); },
    clear: () => {
      if (!owns() || pending.current) return;
      const sourceControl = origin.current;
      setState(old => ({ ...empty(scope), outcomes: old.scope === scope ? old.outcomes : {} }));
      queueMicrotask(() => { if (owns() && origin.current === sourceControl && sourceControl?.isConnected) sourceControl.focus(); });
    } };
}
