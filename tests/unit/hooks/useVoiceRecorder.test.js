import { act, renderHook, waitFor } from '@testing-library/react';
import { useVoiceRecorder } from '@features/chat/hooks/useVoiceRecorder';
import { uploadFileForChat } from '@api/chat';

jest.mock('@api/chat', () => ({ uploadFileForChat: jest.fn() }));

const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
};

describe('voice capture ownership', () => {
  const originalRecorder = global.MediaRecorder;
  const originalGetUserMedia = navigator.mediaDevices.getUserMedia;
  const originalAudioContext = window.AudioContext;
  const recorders = [];
  let stopTrack;
  let getUserMedia;
  let stream;

  class Recorder {
    constructor() { this.state = 'inactive'; recorders.push(this); }
    start() { this.state = 'recording'; }
    stop() {
      this.state = 'inactive';
      this.ondataavailable?.({ data: new Blob(['SYNTHETIC_AUDIO']) });
      this.finished = this.onstop?.();
    }
  }

  beforeEach(() => {
    recorders.length = 0;
    stopTrack = jest.fn();
    stream = { getTracks: () => [{ stop: stopTrack }] };
    getUserMedia = jest.fn().mockResolvedValue(stream);
    navigator.mediaDevices.getUserMedia = getUserMedia;
    global.MediaRecorder = Recorder;
    window.AudioContext = undefined;
    uploadFileForChat.mockReset().mockResolvedValue({ extracted_text: 'Принятый голос' });
  });

  afterEach(() => {
    global.MediaRecorder = originalRecorder;
    window.AudioContext = originalAudioContext;
    navigator.mediaDevices.getUserMedia = originalGetUserMedia;
  });

  const mount = (scopeKey = 'thread-a') => {
    const onTranscript = jest.fn();
    const appendTraceEvent = jest.fn();
    const notify = jest.fn();
    const hook = renderHook(({ scope }) => useVoiceRecorder({
      scopeKey: scope, onTranscript, appendTraceEvent, sideEffects: { notify },
      transcriptionMode: 'local', transcriptionModel: 'small',
    }), { initialProps: { scope: scopeKey } });
    return { ...hook, onTranscript, appendTraceEvent, notify };
  };

  it('admits only one permission request while microphone access is pending', async () => {
    const permission = deferred();
    getUserMedia.mockReturnValue(permission.promise);
    const hook = mount();
    let first;
    let second;
    act(() => {
      first = hook.result.current.toggleRecording();
      second = hook.result.current.toggleRecording();
    });
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(hook.result.current.isRequestingPermission).toBe(true);
    await act(async () => { permission.resolve(stream); await Promise.all([first, second]); });
    expect(recorders).toHaveLength(1);
    expect(hook.result.current.isRequestingPermission).toBe(false);
  });

  it('releases late permission after unmount without starting recording or uploading', async () => {
    const permission = deferred();
    getUserMedia.mockReturnValue(permission.promise);
    const hook = mount();
    let starting;
    act(() => { starting = hook.result.current.toggleRecording(); });
    hook.unmount();
    await act(async () => { permission.resolve(stream); await starting; });
    expect(stopTrack).toHaveBeenCalledTimes(1);
    expect(recorders).toHaveLength(0);
    expect(uploadFileForChat).not.toHaveBeenCalled();
  });

  it('does not turn cleanup of an active recording into a transcription request', async () => {
    const hook = mount();
    await act(async () => { await hook.result.current.toggleRecording(); });
    const recorder = recorders[0];
    hook.unmount();
    await act(async () => { await recorder.finished; });
    expect(stopTrack).toHaveBeenCalledTimes(1);
    expect(uploadFileForChat).not.toHaveBeenCalled();
    expect(hook.onTranscript).not.toHaveBeenCalled();
  });

  it('releases acquired audio if recorder construction fails and reports no exception body', async () => {
    global.MediaRecorder = class { constructor() { throw new Error('PRIVATE_RECORDER_BODY'); } };
    const hook = mount();
    await act(async () => { await hook.result.current.toggleRecording(); });
    expect(stopTrack).toHaveBeenCalledTimes(1);
    expect(hook.notify).toHaveBeenCalledWith(expect.objectContaining({ title: 'Микрофон недоступен' }));
    expect(JSON.stringify(hook.notify.mock.calls)).not.toContain('PRIVATE_RECORDER_BODY');
  });

  it('accepts explicit Stop exactly once and keeps capture busy until transcription settles', async () => {
    const delivery = deferred();
    uploadFileForChat.mockReturnValue(delivery.promise);
    const hook = mount();
    await act(async () => { await hook.result.current.toggleRecording(); });
    await act(async () => { await hook.result.current.toggleRecording(); });
    await waitFor(() => expect(uploadFileForChat).toHaveBeenCalledTimes(1));
    expect(hook.result.current.isTranscribing).toBe(true);
    await act(async () => { await hook.result.current.toggleRecording(); });
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    await act(async () => { delivery.resolve({ extracted_text: 'Принятый голос' }); await recorders[0].finished; });
    expect(hook.onTranscript).toHaveBeenCalledWith('Принятый голос');
    expect(hook.result.current.isTranscribing).toBe(false);
    expect(stopTrack).toHaveBeenCalledTimes(1);
  });

  it('aborts observation on unmount and ignores a late accepted transcript', async () => {
    const delivery = deferred();
    uploadFileForChat.mockReturnValue(delivery.promise);
    const hook = mount();
    await act(async () => { await hook.result.current.toggleRecording(); });
    await act(async () => { await hook.result.current.toggleRecording(); });
    await waitFor(() => expect(uploadFileForChat).toHaveBeenCalledTimes(1));
    const options = uploadFileForChat.mock.calls[0][2];
    hook.unmount();
    expect(options.signal?.aborted).toBe(true);
    await act(async () => { delivery.resolve({ extracted_text: 'LATE_PRIVATE_TRANSCRIPT' }); await recorders[0].finished; });
    expect(hook.onTranscript).not.toHaveBeenCalled();
    expect(hook.appendTraceEvent).not.toHaveBeenCalled();
    expect(hook.notify).not.toHaveBeenCalled();
  });

  it('retires pending microphone admission when the thread changes', async () => {
    const permission = deferred();
    getUserMedia.mockReturnValueOnce(permission.promise);
    const hook = mount();
    let starting;
    act(() => { starting = hook.result.current.toggleRecording(); });
    hook.rerender({ scope: 'thread-b' });
    await act(async () => { permission.resolve(stream); await starting; });
    expect(recorders).toHaveLength(0);
    expect(stopTrack).toHaveBeenCalledTimes(1);
    await act(async () => { await hook.result.current.toggleRecording(); });
    expect(recorders).toHaveLength(1);
  });

  it('does not transcribe an empty capture', async () => {
    const hook = mount();
    await act(async () => { await hook.result.current.toggleRecording(); });
    recorders[0].stop = function stopWithoutAudio() {
      this.state = 'inactive';
      this.finished = this.onstop?.();
    };
    await act(async () => { await hook.result.current.toggleRecording(); await recorders[0].finished; });
    expect(uploadFileForChat).not.toHaveBeenCalled();
    expect(hook.result.current.isTranscribing).toBe(false);
    expect(stopTrack).toHaveBeenCalledTimes(1);
    expect(hook.notify).toHaveBeenCalledWith(expect.objectContaining({ title: 'Речь не распознана' }));
  });

  it('does not retry or publish a late transport failure after changing thread', async () => {
    const delivery = deferred();
    uploadFileForChat.mockReturnValue(delivery.promise);
    const hook = mount();
    await act(async () => { await hook.result.current.toggleRecording(); });
    await act(async () => { await hook.result.current.toggleRecording(); });
    await waitFor(() => expect(uploadFileForChat).toHaveBeenCalledTimes(1));
    const signal = uploadFileForChat.mock.calls[0][2].signal;
    const finished = recorders[0].finished;
    hook.rerender({ scope: 'thread-b' });
    expect(signal.aborted).toBe(true);
    await act(async () => { delivery.reject(new Error('PRIVATE_STT_BODY')); await finished; });
    expect(hook.notify).not.toHaveBeenCalled();
    expect(hook.appendTraceEvent).not.toHaveBeenCalled();
    expect(uploadFileForChat).toHaveBeenCalledTimes(1);
  });

  it('does not accept a captured toggle callback from a retired thread', async () => {
    const hook = mount();
    const oldToggle = hook.result.current.toggleRecording;
    hook.rerender({ scope: 'thread-b' });
    await act(async () => { await oldToggle(); });
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it('consumes a duplicate stop callback once without another upload or transcript', async () => {
    const hook = mount();
    await act(async () => { await hook.result.current.toggleRecording(); });
    const stopEvent = recorders[0].onstop;
    await act(async () => { await hook.result.current.toggleRecording(); await recorders[0].finished; });
    await act(async () => { await stopEvent(); });
    expect(uploadFileForChat).toHaveBeenCalledTimes(1);
    expect(hook.onTranscript).toHaveBeenCalledTimes(1);
    expect(stopTrack).toHaveBeenCalledTimes(1);
  });

  it('retires a failed recording without using partial audio or provider error text', async () => {
    const hook = mount();
    await act(async () => { await hook.result.current.toggleRecording(); });
    const staleStop = recorders[0].onstop;
    act(() => recorders[0].onerror({ message: 'PRIVATE_DEVICE_BODY' }));
    await act(async () => { await staleStop(); });
    expect(uploadFileForChat).not.toHaveBeenCalled();
    expect(stopTrack).toHaveBeenCalledTimes(1);
    expect(hook.result.current.isRecording).toBe(false);
    expect(JSON.stringify(hook.notify.mock.calls)).not.toContain('PRIVATE_DEVICE_BODY');
  });
});
