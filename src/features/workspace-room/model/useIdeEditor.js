import { useCallback, useEffect, useRef, useState } from 'react';
import { leaseIdeFile, moveIdeFile, readIdeFile, writeIdeFile } from '@api/ide';
import { ideFile, ideMove, idePath, ideWrite } from './ideReadContracts';
import { ideReviewedConflict } from './ideDraftComparison';
import { getWorkspaceActorSession } from './workspaceSession';

const empty = (scope) => ({ scope, file: null, busy: '', error: '', outcome: '', conflict: null });
const unreviewed = (file) => ({ path: file.path, actualContent: null, diff: '',
  notice: 'Ваш текст не потерян. Сверьте его с файлом в среде перед повторной записью.' });
const message = (error, kind) => {
  if (kind === 'create') return error?.code === 'ide_file_changed' ? 'Такой путь уже существует. Выберите другое имя.' : 'Создание не подтверждено. Обновите дерево и проверьте путь перед повтором.';
  if (kind === 'edit') return 'Не удалось получить право или проверить файл. Черновик не изменён.';
  return error?.status === 409 || error?.response?.status === 409 ? 'Версия или право на правку изменились. Ваш текст сохранён в редакторе.' : 'Запись не подтверждена. Ваш текст остаётся в редакторе; перечитайте файл перед повторной записью.';
};

export function useIdeEditor({ threadId, repositoryId, generation, active, verified = true, onWritten, onMoved, onRecovered, onDirtyChange, onRegisterDraftLifecycle }) {
  const scope = `${threadId}:${repositoryId}:${generation}`;
  const [actorSession] = useState(getWorkspaceActorSession);
  const [state, setState] = useState(() => empty(scope));
  const current = useRef({}); current.current = { scope, active, verified, state, onWritten, onMoved, onRecovered };
  const alive = useRef(false);
  const request = useRef(null);
  const editorRef = useRef(null);
  const held = useRef(null);
  const cleanup = useRef(Promise.resolve());
  const release = useCallback((lease) => {
    if (!lease?.fence) return cleanup.current;
    const pending = Promise.resolve().then(() => leaseIdeFile(lease.threadId, lease.repositoryId,
      { path: lease.path, generation: lease.generation, action: 'release', fence: lease.fence }, undefined, actorSession)).catch(() => {});
    cleanup.current = Promise.all([cleanup.current, pending]).then(() => {});
    return cleanup.current;
  }, [actorSession]);
  const owns = () => alive.current && current.current.scope === scope;
  const eligible = () => owns() && current.current.active && current.current.verified && Boolean(generation) && !request.current;
  useEffect(() => { alive.current = true; return () => { alive.current = false; request.current?.abort(); release(held.current); held.current = null; }; }, [release]);
  useEffect(() => {
    request.current?.abort(); request.current = null;
    release(held.current); held.current = null;
    // Do not erase a dirty draft merely because a runtime observation expired.
    // Thread/repo changes pass the parent navigation guard before this remount.
    setState((old) => old.file && old.scope.startsWith(`${threadId}:${repositoryId}:`)
      ? { ...old, file: { ...old.file, fence: 0 }, conflict: unreviewed(old.file), busy: '', outcome: '',
        error: 'Нет подтверждения прежней версии. Текст остаётся в этом окне; скопируйте его или проверьте файл.' } : empty(scope));
  }, [scope, threadId, repositoryId, release]);
  useEffect(() => {
    if (active && verified) return;
    request.current?.abort(); request.current = null;
    release(held.current); held.current = null;
    setState((old) => ({ ...old, busy: '', file: old.file ? { ...old.file, fence: 0 } : null,
      error: old.busy === 'save' || old.busy === 'create' ? 'Запись не подтверждена. Перечитайте файл перед повторной записью.' : old.error }));
  }, [active, verified, release]);
  const visible = state.scope === scope ? !verified && state.file ? { ...state, file: { ...state.file, fence: 0 } } : state
    : state.file && state.scope.startsWith(`${threadId}:${repositoryId}:`)
    ? { ...state, file: { ...state.file, fence: 0, detached: true } } : empty(scope);
  const dirty = Boolean(visible.file && (visible.file.content !== visible.file.original || visible.file.detached));
  const abandon = useCallback(() => {
    if (!alive.current || current.current.scope !== scope || request.current) return false;
    release(held.current); held.current = null;
    setState(empty(scope)); return true;
  }, [scope, release]);
  useEffect(() => {
    const lease = held.current;
    if (!visible.file?.fence || !lease) return undefined;
    let timer;
    const expire = () => {
      if (held.current !== lease) return;
      const remaining = visible.file.leaseExpiresAt * 1000 - Date.now();
      // JS timers overflow above ~24.8 days and can otherwise fire after 1ms.
      // Recheck the absolute expiry at each bounded wake; never extend the lease.
      if (remaining > 0) { timer = setTimeout(expire, Math.min(remaining, 2 ** 31 - 1)); return; }
      release(lease); held.current = null;
      setState((old) => ({ ...old, file: old.file ? { ...old.file, fence: 0 } : null,
        error: 'Право на правку истекло. Получите его снова; ваш текст не потерян.' }));
    };
    expire();
    return () => clearTimeout(timer);
  }, [visible.file?.fence, visible.file?.leaseExpiresAt, release]);
  useEffect(() => { onDirtyChange?.(dirty, 'ide'); return () => onDirtyChange?.(false, 'ide'); }, [dirty, onDirtyChange]);
  useEffect(() => onRegisterDraftLifecycle?.({ abandon, editorRef }, 'ide'), [onRegisterDraftLifecycle, abandon]);
  const perform = async (kind, file, operation = 'file') => {
    if (!eligible() || !file || !idePath(file.path)) return false;
    const draft = current.current.state.file;
    if (draft && draft.content !== draft.original && (kind === 'create' || draft.path !== file.path)) return false;
    if (kind === 'save' && (!file.fence || file.content === file.original || current.current.state.scope !== scope)) return false;
    if (kind === 'edit' && draft && current.current.state.scope !== scope) return false;
    const controller = new AbortController(); request.current = controller;
    const valid = () => owns() && current.current.active && current.current.verified && request.current === controller && !controller.signal.aborted;
    setState((old) => ({ ...(old.scope === scope ? old : empty(scope)), busy: kind, error: '', outcome: '' }));
    let lease, retained = false;
    try {
      // Refresh/peer transitions can release the same actor's previous fence.
      // Do not reacquire it while an older cleanup is still in flight.
      await cleanup.current;
      if (!valid()) return false;
      lease = await leaseIdeFile(threadId, repositoryId, { path: file.path, generation, action: 'acquire' }, controller.signal, actorSession);
      if (!valid()) return false;
      if (lease.repository_id !== repositoryId || lease.generation !== generation || lease.path !== file.path
        || !Number.isSafeInteger(lease.fence) || lease.fence <= 0 || !Number.isSafeInteger(lease.expires_at)) throw Error();
      if (kind === 'edit') {
        const response = await readIdeFile(threadId, repositoryId, file.path, generation, controller.signal);
        if (!valid()) return false;
        const actual = ideFile(response, repositoryId, file.path, generation);
        if (actual.kind !== 'text' || actual.truncated || actual.digest !== file.digest
          || actual.content !== (file.original ?? file.content)) {
          setState({ scope, file: { ...file, original: file.original ?? file.content, fence: 0 }, busy: kind,
            error: 'Версия файла изменилась. Ваш текст сохранён в редакторе.', outcome: '',
            conflict: ideReviewedConflict(file, actual, generation) });
          return false;
        }
        held.current = { threadId, repositoryId, generation, path: file.path, fence: lease.fence };
        retained = true;
        setState({ scope, file: { ...file, original: file.original ?? file.content, fence: lease.fence, leaseExpiresAt: lease.expires_at }, busy: kind, error: '', outcome: '', conflict: null });
        return true;
      }
      const content = kind === 'create' ? '' : file.content;
      const response = ideWrite(await writeIdeFile(threadId, repositoryId, { path: file.path, generation, operation, content,
        expected_digest: kind === 'create' ? null : file.digest, fence: lease.fence }, controller.signal, actorSession), repositoryId, file.path, generation, operation);
      if (!valid()) return false;
      // A cache/tree consumer cannot downgrade a confirmed write to "unknown".
      try { Promise.resolve(current.current.onWritten?.(response, content)).catch(() => {}); } catch { /* Read refresh is independent. */ }
      if (operation !== 'directory') {
        held.current = { threadId, repositoryId, generation, path: file.path, fence: lease.fence };
        retained = true;
      }
      setState((old) => ({ scope, busy: kind, error: '', conflict: null, outcome: operation === 'directory' ? 'Папка создана.' : 'Записано во временную среду.',
        file: operation === 'directory' ? old.file : { ...file, kind: 'text', truncated: false, content: old.file?.path === file.path && kind !== 'create' ? old.file.content : content,
          original: content, digest: response.digest, fence: lease.fence, leaseExpiresAt: lease.expires_at } }));
      return true;
    } catch (error) {
      if (valid()) {
        const previous = held.current; held.current = null;
        if (previous && previous.fence !== lease?.fence) await release(previous);
        if (valid()) setState((old) => ({ ...old, error: message(error, kind),
          conflict: old.file ? unreviewed(old.file) : null, file: old.file ? { ...old.file, fence: 0 } : null }));
      }
      return false;
    } finally {
      if (lease?.fence && !retained && !(held.current?.path === file.path && held.current?.generation === generation && held.current?.fence === lease.fence))
        await release({ threadId, repositoryId, generation, path: file.path, fence: lease.fence });
      if (request.current === controller) {
        request.current = null;
        if (owns() && current.current.active) setState(old => ({ ...old, busy: '' }));
      }
    }
  };
  const inspect = async () => {
    const file = current.current.state.file;
    if (!eligible() || !file || !idePath(file.path)) return false;
    const controller = new AbortController(); request.current = controller;
    const valid = () => owns() && current.current.active && current.current.verified && request.current === controller && !controller.signal.aborted;
    setState(old => ({ ...old, busy: 'inspect', error: '', outcome: '', conflict: unreviewed(file), file: { ...old.file, fence: 0 } }));
    const previous = held.current; held.current = null;
    try {
      await release(previous);
      if (!valid()) return false;
      const response = await readIdeFile(threadId, repositoryId, file.path, generation, controller.signal);
      if (!valid()) return false;
      const actual = ideFile(response, repositoryId, file.path, generation);
      const conflict = ideReviewedConflict(file, actual, generation);
      setState(old => ({ ...old, conflict }));
      return conflict.actualContent !== null;
    } catch {
      if (valid()) setState(old => ({ ...old, error: 'Не удалось сверить файл. Ваш черновик сохранён; повторите чтение.' }));
      return false;
    } finally {
      if (request.current === controller) {
        request.current = null;
        if (owns() && current.current.active) setState(old => ({ ...old, busy: '' }));
      }
    }
  };
  const loadActual = () => {
    const { file, conflict } = current.current.state;
    if (!eligible() || !file || conflict?.path !== file.path || conflict?.generation !== generation || conflict.actualContent == null) return false;
    const actual = conflict.actual;
    setState({ ...empty(scope), file: { ...actual, original: actual.content, fence: 0 },
      outcome: 'Загружена проверенная версия из среды. Git-коммит не создавался.' });
    try { Promise.resolve(current.current.onRecovered?.({ ...actual, repository_id: repositoryId, generation })).catch(() => {}); } catch { /* Cache refresh cannot erase the reviewed text. */ }
    queueMicrotask(() => { if (owns() && current.current.active) editorRef.current?.focus(); });
    return true;
  };
  const copyDraft = async () => {
    const file = current.current.state.file;
    if (!owns() || !current.current.active || request.current || !file) return false;
    try {
      await navigator.clipboard.writeText(file.content);
      if (!owns() || !current.current.active || current.current.state.file !== file) return false;
      setState(old => ({ ...old, outcome: 'Ваши изменения скопированы.' }));
      return true;
    } catch {
      if (owns() && current.current.active && current.current.state.file === file)
        setState(old => ({ ...old, error: 'Не удалось скопировать текст. Выделите его в редакторе и скопируйте вручную.' }));
      return false;
    }
  };
  const change = (content) => { if (owns() && current.current.active && current.current.verified && !request.current) setState((old) => old.file?.fence && old.scope === scope ? ({ ...old, file: { ...old.file, content }, outcome: '' }) : old); };
  const move = async (file, destination) => {
    const draft = current.current.state.file;
    if (!eligible() || (draft && draft.content !== draft.original) || !idePath(file?.path) || !idePath(destination) || file.path === destination || destination.startsWith(`${file.path}/`)) return false;
    const controller = new AbortController(); request.current = controller;
    const valid = () => owns() && current.current.active && current.current.verified && request.current === controller && !controller.signal.aborted;
    const leases = [];
    setState(old => ({ ...old, busy: 'move', error: '', outcome: '' }));
    try {
      const previous = held.current; held.current = null; await release(previous);
      if (!valid()) return false;
      for (const path of [file.path, destination]) {
        const lease = await leaseIdeFile(threadId, repositoryId, { path, generation, action: 'acquire' }, controller.signal, actorSession);
        if (lease.repository_id !== repositoryId || lease.generation !== generation || lease.path !== path || !Number.isSafeInteger(lease.fence) || lease.fence < 1) throw Error();
        leases.push({ threadId, repositoryId, generation, path, fence: lease.fence });
        if (!valid()) return false;
      }
      const value = ideMove(await moveIdeFile(threadId, repositoryId, { path: file.path, destination, generation, expected_digest: file.digest ?? null,
        fence: leases[0].fence, destination_fence: leases[1].fence }, controller.signal, actorSession), repositoryId, file.path, destination, generation);
      if (!valid()) return false;
      current.current.onMoved(value);
      setState({ ...empty(scope), outcome: file.type === 'dir' ? 'Папка перемещена.' : 'Файл перемещён.' });
      return true;
    } catch (error) {
      if (valid()) setState(old => ({ ...old, busy: '', error: error?.code === 'ide_file_changed' ? 'Путь назначения уже существует или исходник изменился. Ничего не перезаписано.'
        : 'Перемещение не подтверждено. Обновите дерево перед повтором.', file: old.file ? { ...old.file, fence: 0 } : null }));
      return false;
    } finally {
      for (const lease of leases) release(lease);
      if (request.current === controller) request.current = null;
    }
  };
  return { ...visible, dirty, editorRef, change, discard: abandon, move, inspect, loadActual, copyDraft,
    canInspect: Boolean(generation && verified), canReacquire: Boolean(verified && state.scope === scope),
    edit: (file) => perform('edit', file), create: (path, operation) => perform('create', { path }, operation),
    save: () => perform('save', current.current.state.scope === scope ? current.current.state.file : null) };
}
