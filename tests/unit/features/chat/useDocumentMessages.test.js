import { renderHook } from '@testing-library/react';
import { useDocumentMessages } from '@features/chat/hooks/useDocumentMessages';

it('keeps project order and latest proposal without borrowing another document', () => {
  const messages = [
    { id: 'plain' },
    { id: 'one', metadata: { document_project: 'a', document_proposal: 'old' } },
    { id: 'two', metadata: { document_project: 'b', document_proposal: 'foreign' } },
    { id: 'three', metadata: { document_project: 'a', document_proposal: 'new' } },
  ];
  const { result, rerender } = renderHook(({ project }) => useDocumentMessages(messages, project), {
    initialProps: { project: 'a' },
  });
  const first = result.current;
  expect(first.documentMessages.map((message) => message.id)).toEqual(['one', 'three']);
  expect(first.documentProposalId).toBe('new');
  rerender({ project: 'a' });
  expect(result.current).toBe(first);
  rerender({ project: null });
  expect(result.current.documentMessages).toEqual([]);
  expect(result.current.documentProposalId).toBeUndefined();
});
