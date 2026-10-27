import { LibraryPane } from './LibraryPane';

/** The Work and PDF surfaces share one snapshot, copy owner and pagination. */
export function WorkLibraryPane({ work, uploadControl, copyDisabled = false, hasThread = Boolean(work.threadId), presentation, copyActionForItem, libraryOnlyUpload = false, browser }) {
  const library = work.hub.library || {};
  const workspace = work.hub.workspace || {};
  const uploadedId = work.uploadResult?.ok && work.uploadResult?.file?.file_id;
  return <LibraryPane {...library} {...(browser ? { items: browser.items, state: 'ready' } : {})}
    loading={browser ? browser.loading : work.hub.loading} pageError={browser ? browser.error : work.libraryPageError}
    browser={browser}
    workspaceReady={workspace.state === 'ready'} hasThread={hasThread && workspace.state !== 'unselected'}
    busy={work.busy} presentation={presentation} copyDisabled={copyDisabled} onCopy={work.copyFromLibrary} copyActionForItem={copyActionForItem} libraryOnlyUpload={libraryOnlyUpload}
    onLoadMore={work.loadMoreLibrary} hasMore={library.next_cursor != null || library.next_offset != null}
    uploadControl={uploadControl} outcomes={{
      ...(uploadedId ? { [uploadedId]: work.uploadResult.outcome } : {}), ...work.libraryOutcomes,
    }} />;
}
