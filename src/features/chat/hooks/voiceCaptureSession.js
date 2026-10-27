/** Release ownership before invoking browser callbacks; cleanup never uploads. */
export function releaseCaptureStream(session) {
  const stream = session.stream;
  session.stream = null;
  stream?.getTracks().forEach((track) => {
    try { track.stop(); } catch { /* A retired device is already unavailable. */ }
  });
}

export function retireCaptureSession(session) {
  if (!session) return;
  session.controller.abort();
  const recorder = session.recorder;
  if (recorder) {
    recorder.onstop = null;
    recorder.ondataavailable = null;
    recorder.onerror = null;
    try { if (recorder.state !== 'inactive') recorder.stop(); } catch { /* Device retirement is best effort. */ }
  }
  releaseCaptureStream(session);
}
