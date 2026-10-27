const LIMIT = 256;

function categoryOf(request) {
  try {
    const path = new URL(request.url()).pathname;
    if (/\/api\/chats\/[^/]+\/work\/upload$/.test(path)) return 'work_upload';
    if (/\/api\/chats\/[^/]+\/work$/.test(path)) return 'work_snapshot';
    if (path === '/api/chats/work-library') return 'library_page';
    if (/\/api\/chats\/[^/]+\/workspace\//.test(path)) return 'workspace_operation';
    if (/\/api\/chats\/models(?:\/catalog)?$/.test(path)) return 'model_catalog';
    if (path === '/api/chats/') return 'thread_list';
    if (/\/api\/chats\/[^/]+$/.test(path)) return 'thread_history';
    if (path === '/api/profile/me') return 'profile';
    if (request.resourceType() === 'script') return 'javascript';
  } catch {
    // Diagnostics must not retain malformed URLs or transport exceptions.
  }
  return null;
}

// Test-only diagnostics: no request URL/body/headers, identifiers, filenames,
// provider payload or exception text is serialized into the acceptance artifact.
function collectLiveWorkTimings(page, now = Date.now) {
  const pending = new Map();
  const samples = [];
  let dropped = 0;
  const started = (request) => {
    const category = categoryOf(request);
    if (!category) return;
    if (pending.size + samples.length >= LIMIT) { dropped += 1; return; }
    pending.set(request, { category, started: now(), status: 0 });
  };
  const responded = (response) => {
    const entry = pending.get(response.request());
    if (entry) entry.status = response.status();
  };
  const finished = (request, outcome) => {
    const entry = pending.get(request);
    if (!entry) return;
    pending.delete(request);
    samples.push({ category: entry.category, outcome, status: entry.status, elapsed_ms: Math.max(0, now() - entry.started) });
  };
  const completed = (request) => finished(request, 'completed');
  const failed = (request) => finished(request, 'transport_failed');
  page.on('request', started);
  page.on('response', responded);
  page.on('requestfinished', completed);
  page.on('requestfailed', failed);
  return () => {
    page.off('request', started);
    page.off('response', responded);
    page.off('requestfinished', completed);
    page.off('requestfailed', failed);
    const incompleteByCategory = {};
    for (const entry of pending.values()) {
      incompleteByCategory[entry.category] = (incompleteByCategory[entry.category] || 0) + 1;
    }
    const result = { samples: [...samples], incomplete_count: pending.size, incomplete_by_category: incompleteByCategory, dropped };
    pending.clear();
    return result;
  };
}

module.exports = { collectLiveWorkTimings };
