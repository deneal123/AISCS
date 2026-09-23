import { useCallback, useRef, useState } from 'react';
import { clampTraceDetail } from '../utils/trace';

/**
 * Потолок вложений на одно сообщение. Бэкенд к нескольким готов давно —
 * мультимодальный fan-out включается как раз при >= 2 вложениях; ограничение было
 * чисто фронтовым (брался files[0], а у input не стоял multiple).
 */
export const MAX_ATTACHMENTS = 8;

/**
 * Состояние прикреплённых к сообщению файлов (несколько модальностей) и их
 * загрузка через chat API. Управляет списком attachments, скрытым file input и
 * обработчиком выбора файла. Каждое вложение уже содержит extracted_text
 * (VLM-описание/транскрипт/текст), полученный на стороне сервера при загрузке.
 */
export function useFileAttachment({ appendTraceEvent, sideEffects, transcriptionMode = 'local', transcriptionModel = '' }) {
  const [attachments, setAttachments] = useState([]);
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef(null);
  // Пользователь ЯВНО открепил файл крестиком (не программная очистка после отправки).
  // Сигнал бэкенду стереть thread-память файла: иначе follow-up-механизм воскресит
  // прежний файл треда, и «открепил, а он в контексте» — ровно эта жалоба.
  const userDetachedRef = useRef(false);

  const addAttachment = useCallback((result) => {
    setAttachments((prev) => [...prev, result]);
  }, []);

  const removeAttachment = useCallback((index) => {
    userDetachedRef.current = true;
    setAttachments((prev) => prev.filter((_, i) => i !== index));
  }, []);

  // Программная очистка (после отправки) — НЕ открепление: thread-память трогать не надо.
  const clearAttachments = useCallback(() => setAttachments([]), []);

  // Считать и сбросить флаг открепления — sender зовёт при отправке.
  const consumeUserDetached = useCallback(() => {
    const v = userDetachedRef.current;
    userDetachedRef.current = false;
    return v;
  }, []);

  const handleFileUpload = useCallback(async (e) => {
    const picked = Array.from(e.target.files || []);
    e.target.value = '';
    if (!picked.length) return;

    // Свободные слоты считаем ДО загрузки: незачем гонять на сервер файлы, которые
    // всё равно не поместятся.
    const free = MAX_ATTACHMENTS - attachments.length;
    if (free <= 0) {
      sideEffects.notify({
        title: `Максимум ${MAX_ATTACHMENTS} файлов`,
        description: 'Уберите лишние вложения, чтобы добавить новые.',
        status: 'warning', duration: 3000,
      });
      return;
    }
    const files = picked.slice(0, free);
    if (picked.length > free) {
      sideEffects.notify({
        title: `Взято ${free} из ${picked.length}`,
        description: `За раз можно приложить не больше ${MAX_ATTACHMENTS} файлов.`,
        status: 'info', duration: 3000,
      });
    }

    setIsUploading(true);
    try {
      const { uploadFileForChat } = await import('@api/chat');
      // Параллельно, но allSettled: один битый файл не должен утащить за собой
      // остальные — загрузится всё, что смогло.
      const settled = await Promise.allSettled(
        files.map((file) => uploadFileForChat(
          file,
          '',
          {
            transcriptionMode,
            transcriptionModel,
            uploadIntentId: globalThis.crypto?.randomUUID?.(),
          },
        ))
      );

      const failed = [];
      settled.forEach((outcome, i) => {
        if (outcome.status !== 'fulfilled') {
          failed.push({
            name: files[i].name,
            reason: outcome.reason?.code === 'FILE_PERSISTENCE_FAILED'
              ? 'не сохранён в библиотеке'
              : 'не удалось загрузить',
          });
          return;
        }
        const result = outcome.value;
        addAttachment(result);
        if (result.file_type === 'image' && result.vlm_description) {
          appendTraceEvent({ kind: 'done', title: 'Проанализировано фото (MWS Vision)', detail: clampTraceDetail(result.vlm_description) });
        } else if (result.file_type === 'audio') {
          appendTraceEvent({ kind: 'done', title: 'Аудио прикреплено', detail: 'Файл будет отправлен модели как вложение' });
        } else if (result.file_type === 'repo') {
          appendTraceEvent({ kind: 'done', title: `Карта репозитория: ${result.filename}`, detail: 'Разбор AST без обращений к LLM' });
        } else {
          appendTraceEvent({ kind: 'done', title: `Файл подготовлен: ${result.filename}`, detail: `Тип: ${result.file_type || 'unknown'}` });
        }
      });

      const ok = settled.length - failed.length;
      if (ok > 0) {
        sideEffects.notify({
          title: ok === 1 ? `Файл: ${files[settled.findIndex((s) => s.status === 'fulfilled')].name}` : `Загружено файлов: ${ok}`,
          status: 'success', duration: 2500,
        });
      }
      if (failed.length) {
        sideEffects.notify({
          title: `Не удалось загрузить: ${failed.length}`,
          description: failed.map(({ name, reason }) => `${name} — ${reason}`).join('; '),
          status: 'error', duration: 4000,
        });
      }
    } finally {
      setIsUploading(false);
    }
  }, [addAttachment, attachments.length, appendTraceEvent, sideEffects, transcriptionMode, transcriptionModel]);

  return {
    attachments,
    isUploading,
    addAttachment,
    removeAttachment,
    clearAttachments,
    consumeUserDetached,
    fileInputRef,
    handleFileUpload,
  };
}
