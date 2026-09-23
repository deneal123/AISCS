import { useCallback, useRef } from 'react';
import { copyText } from '@utils/clipboard';

export function useMessageActions({ messages, replaceMessages, handleSendMessageRef }) {
  // messages меняется на КАЖДЫЙ стрим-чанк. Если колбэки закрываются над ним
  // напрямую, они пересоздаются на каждый чанк и пробивают memo(ChatMessageItem)
  // — весь список ре-рендерится во время стрима. Читаем актуальный список из рефа,
  // чтобы regenerate/edit оставались ref-стабильными (deps без messages).
  const messagesRef = useRef(messages);
  messagesRef.current = messages;

  const copyMessage = useCallback((text) => {
    if (!text) return;
    copyText(text);
  }, []);

  // modelOverride: undefined → та же модель; '' → Auto; 'id' → конкретная модель.
  const regenerateMessage = useCallback((messageId, modelOverride, routeOverride) => {
    const messages = messagesRef.current;
    const idx = messages.findIndex((message) => message.id === messageId);
    if (idx === -1) return;

    let userIdx = -1;
    for (let i = idx - 1; i >= 0; i -= 1) {
      if (messages[i]?.type === 'user' && messages[i]?.content) {
        userIdx = i;
        break;
      }
    }
    if (userIdx === -1) return;

    const userMessage = messages[userIdx];
    replaceMessages(messages.slice(0, userIdx + 1));
    handleSendMessageRef.current?.(userMessage.content, {
      skipUserAppend: true,
      anchorMessageId: userMessage.id,
      attachmentRefs: userMessage.attachments || [],
      ...(modelOverride !== undefined ? { modelOverride } : {}),
      ...(routeOverride === 'research_pdf_document' ? { routeOverride } : {}),
    });
  }, [replaceMessages, handleSendMessageRef]);

  // Правка и переотправка любого пользовательского хода: отбрасываем это
  // сообщение и всё, что после него, затем отправляем новый текст как свежий
  // ход (тот же паттерн truncate+resend, что у regenerate). anchorMessageId
  // переиспользуем, чтобы трейс привязался к тому же якорю.
  const editMessage = useCallback((messageId, newText) => {
    const messages = messagesRef.current;
    const trimmed = typeof newText === 'string' ? newText.trim() : '';
    if (!trimmed) return;
    const idx = messages.findIndex((message) => message.id === messageId);
    if (idx === -1) return;
    if (messages[idx]?.type !== 'user') return;

    replaceMessages(messages.slice(0, idx));
    handleSendMessageRef.current?.(trimmed, { anchorMessageId: messageId });
  }, [replaceMessages, handleSendMessageRef]);

  return {
    copyMessage,
    regenerateMessage,
    editMessage,
  };
}
