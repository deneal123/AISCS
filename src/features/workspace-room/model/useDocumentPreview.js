import { useCallback, useEffect, useRef, useState } from 'react';
import { useWorkActionOwner } from './useWorkActionOwner';

// A downloaded blob belongs to one exact thread/build/artifact, not to the
// component that happens to be displaying Document Forge when it arrives.
export function useDocumentPreview({ threadId, build, active = true, projectPath = '' }) {
  const artifactId = build?.artifacts?.find((item) => item.role === 'pdf')?.artifact_id;
  const buildId = build?.build_id;
  const scope = `${threadId || ''}/${buildId || ''}/${artifactId || ''}`;
  const resourceScope = projectPath ? `${threadId}/${projectPath}` : `${scope}/${active}`;
  const currentScope = useRef(scope);
  currentScope.current = scope;
  const currentActive = useRef(active);
  currentActive.current = active;
  const request = useRef(null);
  const objectUrl = useRef('');
  const [previewUrl, setPreviewUrl] = useState('');
  const [previewError, setPreviewError] = useState(false);
  const { busy: previewBusy, begin, owns, finish } = useWorkActionOwner({ threadId, active });

  useEffect(() => {
    setPreviewError(false);
    return () => {
      if (request.current) {
        request.current.controller.abort();
        finish(request.current.ticket);
        request.current = null;
      }
    };
  }, [scope, active, finish]);
  useEffect(() => {
    setPreviewUrl('');
    return () => {
      if (objectUrl.current) {
        URL.revokeObjectURL(objectUrl.current);
        objectUrl.current = '';
      }
    };
  }, [resourceScope]);

  const openPreview = useCallback(async () => {
    if (!buildId || !artifactId || currentScope.current !== scope) return null;
    const ticket = begin(threadId, 'preview');
    if (!ticket) return null;
    const controller = new AbortController();
    request.current = { ticket, controller };
    const isCurrent = () => owns(ticket) && !controller.signal.aborted
      && currentScope.current === scope && currentActive.current;
    setPreviewError(false);
    try {
      const { downloadDocumentArtifact } = await import('@api/chat');
      if (!isCurrent()) return null;
      const blob = await downloadDocumentArtifact(threadId, buildId, artifactId, {
        signal: controller.signal,
      });
      if (!isCurrent()) return null;
      const next = URL.createObjectURL(blob);
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
      objectUrl.current = next;
      setPreviewUrl(next);
      return next;
    } catch {
      if (isCurrent()) setPreviewError(true);
      return null;
    } finally {
      if (request.current?.ticket === ticket) request.current = null;
      finish(ticket);
    }
  }, [artifactId, begin, buildId, finish, owns, scope, threadId]);

  return { previewUrl, previewError, previewBusy: Boolean(previewBusy), openPreview };
}
