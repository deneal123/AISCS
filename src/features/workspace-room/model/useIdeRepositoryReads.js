import { useCallback, useEffect, useRef, useState } from 'react';
import { getIdeRuntime, readIdeFile, readIdeTree } from '@api/ide';
import { ideFile, idePath, ideRuntime, ideTree, ideWrite } from './ideReadContracts';

export const IDE_OPEN_FILE_LIMIT = 8;
const empty = (scope) => ({ scope, loading: false, error: false, observationExpired: false, runtime: null, tree: null, file: null, files: [], fileLoading: false, fileError: false, requestedPath: '' });

/** Frozen thread/repo/generation/path per request; no legacy workspace fallback. */
export function useIdeRepositoryReads({ threadId, repositoryId, active }) {
  const scope = `${threadId || ''}:${repositoryId || ''}`;
  const [state, setState] = useState(() => empty(scope));
  const visit = useRef({ scope, active: false, id: 0 });
  if (visit.current.scope !== scope || (active && !visit.current.active)) visit.current.id += 1;
  visit.current.scope = scope; visit.current.active = active;
  const pending = useRef({});
  const current = useRef({});
  current.current = { scope, active, state };
  const alive = useRef(false);
  const observation = useRef({ scope, until: 0 });
  const abort = useCallback(() => {
    Object.values(pending.current).forEach((controller) => controller.abort());
    pending.current = {};
  }, []);
  useEffect(() => { alive.current = true; return () => { alive.current = false; abort(); }; }, [abort]);
  const eligible = useCallback(() => alive.current && current.current.active && current.current.scope === scope && Boolean(repositoryId), [scope, repositoryId]);
  const start = useCallback((kind) => {
    if (!eligible()) return null;
    pending.current[kind]?.abort();
    const controller = new AbortController();
    pending.current[kind] = controller;
    return { signal: controller.signal, owns: () => eligible() && pending.current[kind] === controller && !controller.signal.aborted,
      finish: () => { if (pending.current[kind] === controller) delete pending.current[kind]; } };
  }, [eligible]);
  const load = useCallback(async ({ fresh = false, observePending = false } = {}) => {
    const ticket = start('tree');
    if (!ticket) return;
    const visitId = visit.current.id;
    if (!observePending) observation.current = { scope, until: 0 };
    pending.current.file?.abort();
    delete pending.current.file;
    setState((old) => ({ ...(old.scope === scope ? old : empty(scope)), loading: true, error: false, observationExpired: false, fileLoading: false }));
    try {
      const runtime = ideRuntime(await getIdeRuntime(threadId, repositoryId, ticket.signal), repositoryId);
      if (!ticket.owns()) return;
      const tree = runtime.state === 'ready' ? ideTree(await readIdeTree(threadId, repositoryId, null, ticket.signal), repositoryId) : null;
      if (!ticket.owns()) return;
      const selected = current.current.state.file;
      let reread = null;
      if (fresh && selected && tree && tree.entries.some(entry => entry.path === selected.path && entry.type === 'file')) {
        reread = ideFile(await readIdeFile(threadId, repositoryId, selected.path, tree.generation, ticket.signal), repositoryId, selected.path, tree.generation);
        if (!ticket.owns()) return;
      }
      setState((old) => {
        const same = Boolean(tree && tree.generation === old.tree?.generation);
        const files = fresh ? reread ? [reread] : [] : same ? old.files.filter((file) => tree.entries.some((entry) => entry.path === file.path && entry.type === 'file')) : [];
        return { ...empty(scope), visitId, runtime, tree, files, file: files.find((file) => file.path === old.file?.path) || null, loading: false };
      });
    } catch {
      if (ticket.owns()) setState((old) => ({ ...old, loading: false, error: true }));
    } finally { ticket.finish(); }
  }, [start, scope, threadId, repositoryId]);
  useEffect(() => {
    if (active && repositoryId) void load();
    return abort;
  }, [active, repositoryId, load, abort]);
  const visible = state.scope === scope ? state : empty(scope);
  const runtimeState = visible.runtime?.state;
  useEffect(() => {
    if (!active || !['pending', 'dispatching'].includes(runtimeState)) {
      observation.current = { scope, until: 0 }; return;
    }
    if (visible.loading || visible.error || visible.observationExpired) return;
    if (observation.current.scope !== scope || !observation.current.until) observation.current = { scope, until: Date.now() + 30000 };
    const timer = setTimeout(() => {
      if (!eligible()) return;
      if (Date.now() >= observation.current.until) setState(old => ({ ...old, observationExpired: true }));
      else void load({ observePending: true });
    }, Math.max(0, Math.min(1200, observation.current.until - Date.now())));
    return () => clearTimeout(timer);
  }, [active, runtimeState, visible.loading, visible.error, visible.observationExpired, scope, load, eligible]);
  const open = useCallback(async (path, { refresh = false } = {}) => {
    if (!eligible() || current.current.state !== state || state.scope !== scope || state.loading || !state.tree || !idePath(path)
      || !state.tree.entries.some((item) => item.path === path && item.type === 'file')) return false;
    const generation = state.tree.generation;
    const cached = state.files.find((file) => file.path === path);
    if (cached && !refresh) {
      pending.current.file?.abort();
      delete pending.current.file;
      setState((old) => ({ ...old, file: cached, fileLoading: false, fileError: false, requestedPath: path }));
      return true;
    }
    const ticket = start('file');
    if (!ticket) return false;
    setState((old) => ({ ...old, fileLoading: true, fileError: false, requestedPath: path }));
    try {
      const file = ideFile(await readIdeFile(threadId, repositoryId, path, generation, ticket.signal), repositoryId, path, generation);
      if (!ticket.owns()) return false;
      setState((old) => {
        if (old.tree?.generation !== generation) return old;
        // Bounded memory-only read tabs, never drafts or a durable source copy.
        const files = old.files.some((item) => item.path === path)
          ? old.files.map((item) => item.path === path ? file : item)
          : [...old.files, file].slice(-IDE_OPEN_FILE_LIMIT);
        return { ...old, files, file, fileLoading: false, fileError: false };
      });
      return true;
    } catch {
      if (ticket.owns()) setState((old) => ({ ...old, fileLoading: false, fileError: true }));
      return false;
    } finally { ticket.finish(); }
  }, [eligible, state, scope, start, threadId, repositoryId]);
  const close = useCallback((path) => {
    if (!eligible() || current.current.state !== state || state.scope !== scope || state.loading || state.fileLoading) return;
    setState((old) => {
      const index = old.files.findIndex((file) => file.path === path);
      if (index < 0) return old;
      const files = old.files.filter((file) => file.path !== path);
      const file = old.file?.path === path ? files[Math.min(index, files.length - 1)] || null : old.file;
      return { ...old, files, file, fileError: false, requestedPath: file?.path || '' };
    });
  }, [eligible, state, scope]);
  const acceptWrite = (value, content) => {
    if (!eligible() || !state.tree || current.current.state !== state) return false;
    const operation = value.kind === 'dir' ? 'directory' : 'file';
    ideWrite(value, repositoryId, value.path, state.tree.generation, operation);
    pending.current.file?.abort(); delete pending.current.file;
    setState((old) => {
      if (old.tree?.generation !== value.generation) return old;
      const entries = old.tree.entries.filter((item) => item.path !== value.path);
      entries.unshift({ path: value.path, type: value.kind, size: value.size, incomplete: false });
      const tree = { ...old.tree, entries: entries.slice(0, 400), truncated: old.tree.truncated || entries.length > 400 };
      if (operation === 'directory') return { ...old, tree };
      const file = ideFile({ ...value, kind: 'text', content, truncated: false }, repositoryId, value.path, value.generation);
      const files = old.files.some((item) => item.path === value.path) ? old.files.map((item) => item.path === value.path ? file : item) : [...old.files, file].slice(-IDE_OPEN_FILE_LIMIT);
      return { ...old, tree, file, files, fileError: false, fileLoading: false };
    });
    return true;
  };
  const acceptRead = (value) => {
    if (!eligible() || !state.tree || current.current.state !== state) return false;
    const file = ideFile(value, repositoryId, value.path, state.tree.generation);
    pending.current.file?.abort(); delete pending.current.file;
    setState(old => {
      if (old.tree?.generation !== value.generation || old.file?.path !== file.path) return old;
      return { ...old, file, files: old.files.map(item => item.path === file.path ? file : item),
        fileLoading: false, fileError: false };
    });
    return true;
  };
  const acceptMove = (value) => {
    if (!eligible() || !state.tree || current.current.state !== state || value.generation !== state.tree.generation) return false;
    pending.current.file?.abort(); delete pending.current.file;
    setState(old => {
      if (old.tree?.generation !== value.generation) return old;
      const under = (path, parent) => path === parent || path.startsWith(`${parent}/`);
      const retarget = path => under(path, value.moved_from) ? value.path + path.slice(value.moved_from.length) : path;
      const entries = old.tree.entries.filter(item => !under(item.path, value.path)).map(item => ({ ...item, path: retarget(item.path), ...(item.path === value.moved_from ? { size: value.size } : {}) }));
      const files = old.files.filter(file => !under(file.path, value.path)).map(file => ({ ...file, path: retarget(file.path) }));
      return { ...old, tree: { ...old.tree, entries }, files, file: old.file ? files.find(file => file.path === retarget(old.file.path)) || null : null,
        fileLoading: false, fileError: false, requestedPath: retarget(old.requestedPath || '') };
    });
    return true;
  };
  return { ...visible, validated: Boolean(active && visible.visitId === visit.current.id && !visible.loading && !visible.error), load, open, close, acceptWrite, acceptRead, acceptMove };
}
