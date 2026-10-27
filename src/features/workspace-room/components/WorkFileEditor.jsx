import { WorkspaceEditor } from './WorkspaceEditor';

/** Bind the same fenced file-editing operations in Work and PDF source views. */
export function WorkFileEditor({ work, editorRef }) {
  const available = work.hub?.workspace?.state === 'ready';
  return (
    <WorkspaceEditor
      file={available ? work.file : { ...work.file, fence: 0, leaseStatus: 'unavailable' }}
      dirty={work.dirty}
      busy={work.busy}
      conflict={work.conflict}
      revert={work.revert}
      onChange={(content) => work.setFile((old) => ({ ...old, content }))}
      onSave={work.save}
      onDiscard={work.discard}
      onReacquire={work.reacquireLease}
      canReacquire={available}
      onCopyDraft={work.copyDraft}
      onLoadActual={work.loadActual}
      onCloseRevert={() => work.setRevert(null)}
      onApplyRevert={work.applyRevert}
      editorRef={editorRef}
    />
  );
}
