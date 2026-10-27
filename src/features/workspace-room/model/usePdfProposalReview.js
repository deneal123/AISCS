import { useEffect, useMemo, useRef, useState } from 'react';
import { getDocumentProposal, saveDocumentDraft } from '@api/chat';
import { getWorkspaceActorSession } from './workspaceSession';
import { useWorkActionOwner } from './useWorkActionOwner';
import { proposalChanges, validProposal } from './pdfProposal';

export function usePdfProposalReview({ threadId, proposalId, project, work, dirty, active }) {
  const scope = JSON.stringify([threadId, project?.path, proposalId]);
  // The shared owner fences the complete resource, not just a thread's lifetime.
  const { busy, begin, owns, finish } = useWorkActionOwner({ threadId: scope, active });
  const [open, setOpen] = useState(false);
  const [viewScope, setViewScope] = useState(scope);
  const [value, setValue] = useState(null);
  const [error, setError] = useState('');
  const [outcome, setOutcome] = useState(null);
  const read = useRef(null);
  const current = useRef(null);
  const scopedValue = viewScope === scope ? value : null;
  const changed = useMemo(() => proposalChanges(scopedValue), [scopedValue]);
  current.current = { scope, active, dirty, value: scopedValue, error, busy };
  const isCurrent = (ticket) => owns(ticket) && current.current.scope === scope && current.current.active;
  const stopRead = () => {
    if (!read.current) return;
    read.current.controller.abort();
    finish(read.current.ticket);
    read.current = null;
  };
  useEffect(() => {
    setViewScope(scope); setOpen(false); setValue(null); setError('');
    return () => {
      if (read.current) { read.current.controller.abort(); finish(read.current.ticket); read.current = null; }
    };
  }, [scope, active, finish]);
  const close = () => {
    if (current.current.busy === 'apply' || current.current.scope !== scope || !current.current.active) return;
    stopRead(); setOpen(false);
  };
  const review = async () => {
    if (!active || !project?.path || !proposalId || current.current.scope !== scope) return;
    const ticket = begin(scope, 'read');
    if (!ticket) return;
    const controller = new AbortController();
    read.current = { ticket, controller };
    setViewScope(scope); setOpen(true); setValue(null); setError('');
    try {
      const next = await getDocumentProposal(threadId, proposalId, { signal: controller.signal });
      if (controller.signal.aborted || !isCurrent(ticket)) return;
      if (!validProposal(next, project.path, proposalId)) throw new Error('invalid_proposal');
      setValue(next);
    } catch {
      if (!controller.signal.aborted && isCurrent(ticket)) setError('Не удалось загрузить правки. Повторите просмотр.');
    } finally {
      if (read.current?.ticket === ticket) read.current = null;
      finish(ticket);
    }
  };
  const refreshDocument = async (ticket, path) => {
    try {
      if (!isCurrent(ticket)) return;
      const projectResult = await work.document.loadProject(path);
      if (!isCurrent(ticket)) return;
      const authoringResult = await work.document.loadAuthoring(path);
      if (!isCurrent(ticket)) return;
      const snapshot = await work.load({ background: true });
      if (!isCurrent(ticket)) return;
      const refreshFailed = !projectResult || !authoringResult || !snapshot;
      setOutcome({ scope, refreshFailed, text: refreshFailed
        ? 'Правки сохранены, но обновить редактор не удалось.' : 'Правки применены. Пересоберите PDF, чтобы обновить превью.' });
    } catch {
      if (isCurrent(ticket)) setOutcome({ scope, refreshFailed: true, text: 'Правки сохранены, но обновить редактор не удалось.' });
    }
  };
  const apply = async () => {
    if (!active || dirty || error || !value || value.stale || !changed.length
      || current.current.scope !== scope || current.current.dirty || current.current.value !== value || current.current.error) return;
    const ticket = begin(scope, 'apply');
    if (!ticket) return;
    const actorSession = getWorkspaceActorSession();
    let lease; let api;
    try {
      api = await import('@api/chat');
      if (!isCurrent(ticket) || current.current.dirty) return;
      lease = await api.acquireWorkspaceLease(threadId, value.path, { actorSession });
      if (!isCurrent(ticket) || current.current.dirty) return;
      await saveDocumentDraft(threadId, {
        path: value.path, draft: value.draft, expected_revision: value.expected_revision,
        authoring_version: value.authoring_version, draft_digest: value.draft_digest, fence: Number(lease.fence),
      }, { actorSession });
      if (!isCurrent(ticket)) return;
      setOpen(false); setOutcome({ scope, text: 'Правки применены. Обновляю документ…' });
      await refreshDocument(ticket, value.path);
    } catch (failure) {
      if (isCurrent(ticket)) {
        const conflict = Number(failure?.status || failure?.response?.status) === 409;
        if (conflict) setValue((old) => old && ({ ...old, stale: true }));
        setError(conflict ? 'Документ изменился. Правки не применены; запросите новое предложение.'
          : 'Не удалось подтвердить применение. Обновите просмотр перед повторной попыткой.');
      }
    } finally {
      if (lease?.fence) await api.releaseWorkspaceLease(threadId, value.path, Number(lease.fence), { actorSession }).catch(() => {});
      finish(ticket);
    }
  };
  const retryRefresh = async () => {
    if (dirty || current.current.dirty) return;
    const ticket = begin(scope, 'refresh');
    if (!ticket) return;
    try { await refreshDocument(ticket, project.path); } finally { finish(ticket); }
  };
  const reject = () => {
    if (current.current.busy || !current.current.active || current.current.scope !== scope) return;
    close(); setOutcome({ scope, text: 'Правки отклонены. Документ не изменён.' });
  };
  return { open: viewScope === scope && open, value: scopedValue, error: viewScope === scope ? error : '',
    busy, outcome: outcome?.scope === scope ? outcome : null,
    changed, close, review, apply, reject, retryRefresh };
}
