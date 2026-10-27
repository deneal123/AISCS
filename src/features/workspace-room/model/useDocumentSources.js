import { useCallback, useEffect, useRef, useState } from 'react';
import { getDocumentSources } from '@api/chat';

/** Source metadata is private REST data, never a workspace snapshot or WS payload. */
export function useDocumentSources({ threadId, project, enabled, refreshProject }) {
  const key = JSON.stringify([threadId, project?.path, project?.revision, project?.source_digest]);
  const current = useRef(null);
  const request = useRef(null);
  const retrying = useRef(null);
  const settledKey = useRef('');
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const [state, setState] = useState({ key: '', status: 'idle', sources: [], unresolved: 0 });
  current.current = { key, enabled };
  const load = useCallback(async () => {
    if (!mounted.current || !enabled || !current.current?.enabled || !threadId || !project?.path || current.current?.key !== key) return;
    if (request.current?.key === key) return;
    request.current?.controller.abort();
    const ticket = { key, controller: new AbortController() };
    request.current = ticket;
    setState((old) => ({ key, status: 'loading', sources: old.key === key ? old.sources : [], unresolved: 0 }));
    try {
      const result = await getDocumentSources(threadId, project.path, { signal: ticket.controller.signal });
      if (ticket.controller.signal.aborted || current.current?.key !== key || !current.current.enabled) return;
      if (result?.revision !== project.revision || !Array.isArray(result?.sources)
        || (project.source_digest && result.source_digest !== project.source_digest)) throw new Error('stale_sources');
      const seen = new Set();
      const sources = result.sources.map((source) => {
        if (!Number.isInteger(source?.source_id) || source.source_id < 1 || source.source_id > 10000
          || seen.has(source.source_id)) throw new Error('invalid_sources');
        seen.add(source.source_id);
        return { ...source, value: String(source.source_id),
          label: [(typeof source.title === 'string' && source.title.trim()) || `Источник ${source.source_id}`,
            typeof source.year === 'string' && source.year].filter(Boolean).join(' · ') };
      });
      setState({ key, status: 'ready', sources, unresolved: Number(result.unresolved_count) || 0 });
      settledKey.current = key;
    } catch {
      if (!ticket.controller.signal.aborted && current.current?.key === key && current.current.enabled) {
        setState({ key, status: 'unavailable', sources: [], unresolved: 0 });
      }
    } finally {
      if (request.current === ticket) request.current = null;
    }
  }, [enabled, key, project?.path, project?.revision, project?.source_digest, threadId]);
  useEffect(() => {
    if (enabled && settledKey.current !== key) void load();
    return () => { request.current?.controller.abort(); request.current = null; };
  }, [enabled, key, load]);
  const retry = useCallback(async () => {
    if (!mounted.current || !current.current?.enabled || current.current.key !== key
      || request.current || retrying.current) return;
    const ticket = { key };
    retrying.current = ticket;
    setState({ key, status: 'loading', sources: [], unresolved: 0 });
    try {
      await refreshProject?.(project.path);
      if (mounted.current && current.current?.key === key && current.current.enabled) await load();
    } catch {
      if (mounted.current && current.current?.key === key && current.current.enabled) {
        setState({ key, status: 'unavailable', sources: [], unresolved: 0 });
      }
    } finally {
      if (retrying.current === ticket) retrying.current = null;
    }
  }, [key, load, project?.path, refreshProject]);
  const visible = state.key === key ? state : { status: enabled ? 'loading' : 'idle', sources: [], unresolved: 0 };
  return { ...visible, load, retry };
}
