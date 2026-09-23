const STORAGE_KEY = 'gpthub.workspace.actor-session';

let memorySession = '';

function createSession() {
  if (typeof globalThis.crypto?.randomUUID === 'function') {
    return globalThis.crypto.randomUUID();
  }
  const bytes = new Uint8Array(18);
  globalThis.crypto?.getRandomValues?.(bytes);
  const encoded = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('');
  return encoded || `${Date.now()}-${Math.random().toString(36).slice(2, 18)}`;
}
/**
 * One opaque identity per browser tab.
 *
 * Ownership and the `ui` role are still derived server-side from auth.  This
 * token only lets the lease layer distinguish two editors belonging to the
 * same account. Session storage intentionally does not synchronize tabs.
 */
export function getWorkspaceActorSession() {
  if (typeof window === 'undefined') {
    if (!memorySession) memorySession = createSession();
    return memorySession;
  }
  try {
    const existing = window.sessionStorage.getItem(STORAGE_KEY);
    if (existing) return existing;
    const created = createSession();
    window.sessionStorage.setItem(STORAGE_KEY, created);
    return created;
  } catch {
    if (!memorySession) memorySession = createSession();
    return memorySession;
  }
}
