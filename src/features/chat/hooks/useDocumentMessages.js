import { useMemo } from 'react';

/** UI projection only; project authorization remains on the server. */
export function useDocumentMessages(messages, projectId) {
  return useMemo(() => {
    const documentMessages = projectId ? messages.filter((message) =>
      message.metadata?.document_project === projectId) : [];
    const documentProposalId = documentMessages.findLast((message) =>
      message.metadata?.document_proposal)?.metadata.document_proposal;
    return { documentMessages, documentProposalId };
  }, [messages, projectId]);
}
