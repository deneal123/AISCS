import { act, renderHook, waitFor } from '@testing-library/react';
import { useFileAttachment } from '@/features/chat/hooks/useFileAttachment';
import { uploadFileForChat } from '@/shared/api/chat';

jest.mock('@/shared/api/chat', () => ({
  uploadFileForChat: jest.fn(),
}));

describe('useFileAttachment', () => {
  it('passes transcription settings as the upload options and never creates a phantom attachment', async () => {
    uploadFileForChat.mockResolvedValue({
      file_id: 'opaque-file-id',
      filename: 'recording.mp3',
      file_type: 'audio',
    });
    const notify = jest.fn();
    const { result } = renderHook(() => useFileAttachment({
      appendTraceEvent: jest.fn(),
      sideEffects: { notify },
      transcriptionMode: 'local',
      transcriptionModel: 'small',
    }));
    const file = new File(['audio'], 'recording.mp3', { type: 'audio/mpeg' });

    await act(async () => {
      await result.current.handleFileUpload({ target: { files: [file], value: 'chosen' } });
    });

    await waitFor(() => expect(uploadFileForChat).toHaveBeenCalledWith(
      file,
      '',
      { transcriptionMode: 'local', transcriptionModel: 'small' },
    ));
    expect(result.current.attachments).toEqual([expect.objectContaining({ file_id: 'opaque-file-id' })]);
    expect(notify).toHaveBeenCalledWith(expect.objectContaining({ status: 'success' }));
  });

  it('shows a safe file-specific failure and keeps the attachment list empty', async () => {
    const failure = Object.assign(new Error('not durable'), { code: 'FILE_PERSISTENCE_FAILED' });
    uploadFileForChat.mockRejectedValue(failure);
    const notify = jest.fn();
    const { result } = renderHook(() => useFileAttachment({
      appendTraceEvent: jest.fn(),
      sideEffects: { notify },
    }));
    const file = new File(['body'], 'draft.txt', { type: 'text/plain' });

    await act(async () => {
      await result.current.handleFileUpload({ target: { files: [file], value: 'chosen' } });
    });

    await waitFor(() => expect(notify).toHaveBeenCalledWith(expect.objectContaining({
      status: 'error',
      description: 'draft.txt — не сохранён в библиотеке',
    })));
    expect(result.current.attachments).toEqual([]);
  });
});
