import { useCallback, useEffect, useRef, useState } from 'react';
import { releaseCaptureStream, retireCaptureSession } from './voiceCaptureSession';

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
  let ctx;
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) throw new Error('no AudioContext');
    const arrayBuffer = await blob.arrayBuffer();
    ctx = new AC();
    const decoded = await ctx.decodeAudioData(arrayBuffer.slice(0));
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
  } finally {
    try { await ctx?.close?.(); } catch { /* Decoder cleanup must not expose SDK errors. */ }
  }
}

export function useVoiceRecorder({ scopeKey, onTranscript, appendTraceEvent, sideEffects, transcriptionMode = 'local', transcriptionModel = '' }) {
  const [isRecording, setIsRecording] = useState(false);
  const [isRequestingPermission, setIsRequestingPermission] = useState(false);
  // Пока идёт распознавание (upload+STT) — держим состояние, чтобы заблокировать
  // отправку (иначе транскрипт уйдёт пустым — гонка) и показать индикатор.
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [elapsedSec, setElapsedSec] = useState(0);
  const sessionRef = useRef(null);
  const mountedRef = useRef(false);
  const activeScopeRef = useRef(scopeKey);
  activeScopeRef.current = scopeKey;
  const timerRef = useRef(null);

  const stopTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    setIsRecording(false);
    setIsRequestingPermission(false);
    setIsTranscribing(false);
    setElapsedSec(0);
    return () => {
      mountedRef.current = false;
      const session = sessionRef.current;
      sessionRef.current = null;
      stopTimer();
      retireCaptureSession(session);
    };
  }, [scopeKey, stopTimer]);

  const toggleRecording = useCallback(async () => {
    if (!mountedRef.current || activeScopeRef.current !== scopeKey) return;
    const previous = sessionRef.current;
    if (previous) {
      if (previous.phase === 'recording') {
        previous.phase = 'stopping';
        setIsRecording(false);
        setIsTranscribing(true);
        stopTimer();
        try { previous.recorder.stop(); } catch {
          sessionRef.current = null;
          retireCaptureSession(previous);
          setIsTranscribing(false);
          sideEffects.notify({ title: 'Ошибка записи', status: 'error', duration: 3000 });
        }
      }
      return;
    }
    const session = { scope: scopeKey, phase: 'starting', stream: null, recorder: null, stopHandled: false, controller: new AbortController() };
    sessionRef.current = session;
    setIsRequestingPermission(true);
    const ownsSession = () => mountedRef.current && activeScopeRef.current === session.scope && sessionRef.current === session;
    try {
      const isSecure = window.isSecureContext || window.location.protocol === 'https:' || window.location.hostname === 'localhost';
      if (!isSecure || !navigator.mediaDevices) {
        sessionRef.current = null;
        setIsRequestingPermission(false);
        sideEffects.notify({ title: 'Микрофон недоступен', description: 'Требуется HTTPS-соединение.', status: 'warning', duration: 4000 });
        return;
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      session.stream = stream;
      if (!ownsSession()) { releaseCaptureStream(session); return; }
      setIsRequestingPermission(false);
      const mediaRecorder = new MediaRecorder(stream);
      session.recorder = mediaRecorder;
      const chunks = [];
      mediaRecorder.ondataavailable = (e) => { if (ownsSession() && e.data?.size) chunks.push(e.data); };
      mediaRecorder.onstop = async () => {
        if (!ownsSession() || session.stopHandled) return;
        session.stopHandled = true;
        session.phase = 'transcribing';
        stopTimer();
        releaseCaptureStream(session);
        const blob = new Blob(chunks, { type: 'audio/webm' });
        setIsRecording(false);
        if (!blob.size) {
          sessionRef.current = null;
          setIsTranscribing(false);
          sideEffects.notify({ title: 'Речь не распознана', description: 'Попробуйте записать ещё раз', status: 'warning', duration: 2500 });
          return;
        }
        setIsTranscribing(true);
        try {
          const file = await toUploadableAudio(blob);
          if (!ownsSession()) return;
          const { uploadFileForChat } = await import('@api/chat');
          if (!ownsSession()) return;
          const result = await uploadFileForChat(file, '', { transcriptionMode, transcriptionModel, signal: session.controller.signal });
          if (!ownsSession()) return;
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
          if (ownsSession()) sideEffects.notify({ title: 'Ошибка распознавания', status: 'error', duration: 3000 });
        } finally {
          if (ownsSession()) {
            sessionRef.current = null;
            setIsTranscribing(false);
          }
        }
      };
      mediaRecorder.onerror = () => {
        if (!ownsSession()) return;
        sessionRef.current = null;
        stopTimer();
        retireCaptureSession(session);
        setIsRecording(false);
        setIsTranscribing(false);
        sideEffects.notify({ title: 'Ошибка записи', status: 'error', duration: 3000 });
      };
      mediaRecorder.start();
      if (!ownsSession()) return;
      session.phase = 'recording';
      setIsRecording(true);
      setElapsedSec(0);
      timerRef.current = setInterval(() => setElapsedSec((s) => s + 1), 1000);
    } catch {
      if (ownsSession()) {
        sessionRef.current = null;
        retireCaptureSession(session);
        setIsRequestingPermission(false);
        sideEffects.notify({ title: 'Микрофон недоступен', status: 'error', duration: 3000 });
      }
    }
  }, [scopeKey, onTranscript, appendTraceEvent, sideEffects, stopTimer, transcriptionMode, transcriptionModel]);

  return { isRecording, isRequestingPermission, isTranscribing, elapsedSec, toggleRecording };
}
