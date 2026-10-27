import { useEffect, useState } from 'react';

export function useWorkContextSelection(threadId) {
  const [selection, setSelection] = useState({ threadId, tab: 0, open: false });
  const current = selection.threadId === threadId;

  useEffect(() => {
    setSelection({ threadId, tab: 0, open: false });
  }, [threadId]);

  return {
    tab: current ? selection.tab : 0,
    open: current && selection.open,
    selectTab: (tab) => setSelection((previous) => ({ ...previous, threadId, tab })),
    setOpen: (open) => setSelection((previous) => ({ ...previous, threadId, open })),
  };
}
