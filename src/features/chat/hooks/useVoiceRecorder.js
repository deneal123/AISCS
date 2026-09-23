import { useCallback, useEffect, useRef, useState } from 'react';

// Кодируем AudioBuffer в WAV (16-bit PCM, моно). Аудио-модели (gpt-audio) берут
// wav/mp3, но НЕ webm/opus, который отдаёт MediaRecorder — поэтому конвертируем.
function encodeWav(audioBuffer) {
  const sr = audioBuffer.sampleRate;
  const samples = audioBuffer.getChannelData(0);
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeStr = (o, s) => { for (let i = 0; i < s.length; i += 1) view.setUint8(o + i, s.charCodeAt(i)); };
  writeStr(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  writeStr(8, 'WAVE');
  writeStr(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sr, true);
  view.setUint32(28, sr * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, 'data');
  view.setUint32(40, samples.length * 2, true);
  let o = 44;
  for (let i = 0; i < samples.length; i += 1, o += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([view], { type: 'audio/wav' });
}

// webm/opus → wav 16kHz моно (оптимально для STT + маленький размер). При любой
// ошибке декодирования — возвращаем исходный blob как webm (fail-open).
async function toUploadableAudio(blob) {
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) throw new Error('no AudioContext');
    const arrayBuffer = await blob.arrayBuffer();
    const ctx = new AC();
    const decoded = await ctx.decodeAudioData(arrayBuffer.slice(0));
    if (ctx.close) ctx.close();
    const targetSr = 16000;
    const frames = Math.max(1, Math.ceil(decoded.duration * targetSr));
    const offline = new OfflineAudioContext(1, frames, targetSr);
    const src = offline.createBufferSource();
    src.buffer = decoded;
    src.connect(offline.destination);
    src.start();
    const rendered = await offline.startRendering();
    return new File([encodeWav(rendered)], 'voice.wav', { type: 'audio/wav' });
  } catch {
    return new File([blob], 'voice.webm', { type: 'audio/webm' });
  }
}

export function useVoiceRecorder({ onTranscript, appendTraceEvent, sideEffects, transcriptionMode = 'local', transcriptionModel = '' }) {
  const [isRecording, setIsRecording] = useState(false);
  // Пока идёт распознавание (upload+STT) — держим состояние, чтобы заблокировать
  // отправку (иначе транскрипт уйдёт пустым — гонка) и показать индикатор.
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [elapsedSec, setElapsedSec] = useState(0);
  const mediaRecorderRef = useRef(null);
  const streamRef = useRef(null);
  const timerRef = useRef(null);

  const stopTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => {
      stopTimer();
      if (mediaRecorderRef.current?.state === 'recording') {
        mediaRecorderRef.current.stop();
      }
      mediaRecorderRef.current = null;
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    };
  }, [stopTimer]);

  const toggleRecording = useCallback(async () => {
    if (isRecording) {
      mediaRecorderRef.current?.stop();
      setIsRecording(false);
      stopTimer();
      return;
    }
    try {
      const isSecure = window.isSecureContext || window.location.protocol === 'https:' || window.location.hostname === 'localhost';
      if (!isSecure || !navigator.mediaDevices) {
        sideEffects.notify({ title: 'Микрофон недоступен', description: 'Требуется HTTPS-соединение.', status: 'warning', duration: 4000 });
        return;
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mediaRecorder = new MediaRecorder(stream);
      const chunks = [];
      mediaRecorder.ondataavailable = (e) => chunks.push(e.data);
      mediaRecorder.onstop = async () => {
        stopTimer();
        stream.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        const blob = new Blob(chunks, { type: 'audio/webm' });
        setIsTranscribing(true);
        try {
          const file = await toUploadableAudio(blob);
          const { uploadFileForChat } = await import('@api/chat');
          const result = await uploadFileForChat(file, '', { transcriptionMode, transcriptionModel });
          // Голос = сообщение: транскрипт кладём В КОМПОЗЕР (текст), а не во
          // вложение — можно отправить голосовое одним нажатием, без «.» и без
          // повторной обработки audio_transcribe-агентом.
          const transcript = (result?.extracted_text || '').trim();
          if (transcript) onTranscript?.(transcript);
          appendTraceEvent({ kind: 'done', title: 'Голос распознан', detail: transcript ? `Распознано ${transcript.length} символов` : 'Речь не распознана' });
          sideEffects.notify({
            title: transcript ? 'Голос распознан' : 'Речь не распознана',
            description: transcript ? 'Проверьте текст и отправьте' : 'Попробуйте записать ещё раз',
            status: transcript ? 'success' : 'warning',
            duration: 2500,
          });
        } catch {
          sideEffects.notify({ title: 'Ошибка распознавания', status: 'error', duration: 3000 });
        } finally {
          setIsTranscribing(false);
        }
      };
      mediaRecorder.start();
      mediaRecorderRef.current = mediaRecorder;
      setIsRecording(true);
      setElapsedSec(0);
      timerRef.current = setInterval(() => setElapsedSec((s) => s + 1), 1000);
    } catch {
      sideEffects.notify({ title: 'Микрофон недоступен', status: 'error', duration: 3000 });
    }
  }, [onTranscript, appendTraceEvent, isRecording, sideEffects, stopTimer, transcriptionMode, transcriptionModel]);

  return { isRecording, isTranscribing, elapsedSec, toggleRecording };
}
